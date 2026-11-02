"""Verify seeded patient/doctor workflows through real HTTP and configured Gemini.

No provider mocks. Requires seeded/indexed demo reports and DEMO_PASSWORD.
Does not create appointments or notes; temporarily revokes and restores demo consent.
"""
import argparse
import json
import os
import sys
from urllib.parse import urlparse

import httpx


def checked(response):
    if response.status_code >= 400:
        data = response.json()
        raise RuntimeError(f"HTTP {response.status_code}: {data.get('error', 'Request failed')}")
    return response.json()


def login(client, email, password):
    result = checked(client.post('/api/v1/auth/login', json={'email': email, 'password': password}))
    client.headers['X-CSRF-Token'] = result['csrf_token']
    return result['user']


def verify_answer(client, path, question, document_ids):
    result = checked(client.post(path, json={'message': question}))
    if not result['citations']:
        raise RuntimeError('No supported citations returned; live generation is not verified.')
    for citation in result['citations']:
        if citation['document_id'] not in document_ids:
            raise RuntimeError('Citation escaped the selected patient document set.')
        source = client.get(citation['url'].split('#')[0])
        if source.status_code != 200 or citation['excerpt'] not in source.text:
            raise RuntimeError('Citation excerpt does not match its accessible original.')
    print(json.dumps({'question': question, 'answer': result['answer'],
                      'request_id': result['request_id'], 'citations': result['citations']}), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://localhost:3000')
    parser.add_argument('--origin', default='http://localhost:3000')
    parser.add_argument('--extended', action='store_true', help='Also test glucose comparison and missing clinical-note evidence')
    args = parser.parse_args()
    password = os.getenv('DEMO_PASSWORD', '')
    if not password:
        print('NOT VERIFIED: DEMO_PASSWORD must be supplied locally; no credentials are printed.')
        return 2
    headers = {'Origin': args.origin, 'Host': urlparse(args.origin).netloc, 'X-Requested-With': 'CareConnect'}
    errors = []
    with httpx.Client(base_url=args.base_url, headers=headers, timeout=240) as patient, \
            httpx.Client(base_url=args.base_url, headers=headers, timeout=240) as doctor, \
            httpx.Client(base_url=args.base_url, headers=headers, timeout=240) as unrelated:
        try:
            patient_user = login(patient, 'demo.patient@example.test', password)
            login(doctor, 'demo.doctor@example.test', password)
            login(unrelated, 'demo.unrelated@example.test', password)
            pid = patient_user['id']
            documents = checked(patient.get('/api/v1/documents'))['documents']
            ready = {d['id'] for d in documents if d['state'] == 'READY'}
            if len(ready) < 5:
                raise RuntimeError(f'Demo patient has {len(ready)} indexed reports; index all five first.')
            chart = checked(doctor.get(f'/api/v1/doctor/patients/{pid}'))
            history = checked(doctor.get(f'/api/v1/doctor/patients/{pid}/history'))
            appointments = checked(doctor.get('/api/v1/doctor/appointments'))['appointments']
            assert history['notes'] and any(a['patient_id'] == pid for a in appointments)
            assert unrelated.get(f'/api/v1/doctor/patients/{pid}/documents').status_code == 403
            assert unrelated.post(f'/api/v1/doctor/patients/{pid}/ai/chat', json={'message': 'blood pressure'}).status_code == 403
            first_id = next(iter(ready))
            doctor_source = f'/api/v1/doctor/patients/{pid}/documents/{first_id}/source'
            assert doctor.get(doctor_source).status_code == 200
            assert unrelated.get(doctor_source).status_code == 403
            print(json.dumps({'workflow': 'authorized chart, notes, appointments, sources and unrelated-doctor denial verified',
                              'demo_ready_reports': len(ready)}), flush=True)
            for client, path, question, expected in [
                (patient, '/api/v1/ai/chat', 'What was my latest blood pressure? Include its exact value and report date.', '124'),
                (doctor, f'/api/v1/doctor/patients/{pid}/ai/chat', 'Which report contains the latest hemoglobin result? Give the value, units and date.', '14.6'),
            ]:
                try:
                    result = verify_answer(client, path, question, ready)
                    if expected not in result['answer']:
                        raise RuntimeError('Generated answer did not contain the expected synthetic report value.')
                except RuntimeError as exc:
                    errors.append(str(exc))
                    print(json.dumps({'live_generation': 'NOT VERIFIED', 'error': str(exc)}), flush=True)
            if args.extended:
                try:
                    result = verify_answer(patient, '/api/v1/ai/chat', 'How has my fasting blood glucose changed from July to November 2026? Give dates, values and units.', ready)
                    assert '126' in result['answer'] and '102' in result['answer']
                    missing = checked(patient.post('/api/v1/ai/chat', json={'message': 'What did my doctor record in the clinical note during my last appointment?'}))
                    print(json.dumps({'unsupported_question_answer': missing['answer'], 'citation_count': len(missing['citations'])}), flush=True)
                    if missing['citations']:
                        raise RuntimeError('Missing-note question returned citations instead of the insufficient-evidence form.')
                    print(json.dumps({'missing_note_evidence': 'honest insufficient evidence; notes remain structured only'}), flush=True)
                except (RuntimeError, AssertionError) as exc:
                    errors.append(str(exc) or 'Extended evidence assertions failed')
                    print(json.dumps({'extended_generation': 'NOT VERIFIED', 'error': errors[-1]}), flush=True)
            consent = chart['consent']
            doctor_id = checked(doctor.get('/api/v1/auth/me'))['user']['id']
            path = f'/api/v1/patient/consents/{doctor_id}'
            saved = {k: consent[k] for k in ('records', 'clinical', 'ai')}
            try:
                checked(patient.put(path, json={'records': False, 'clinical': False, 'ai': False}))
                assert doctor.get(doctor_source).status_code == 403
                assert doctor.post(f'/api/v1/doctor/patients/{pid}/ai/chat', json={'message': 'blood pressure'}).status_code == 403
                print(json.dumps({'consent_revocation': 'subsequent source and RAG requests denied'}), flush=True)
            finally:
                checked(patient.put(path, json=saved))
            assert doctor.get(doctor_source).status_code == 200
        except (RuntimeError, AssertionError, httpx.HTTPError) as exc:
            # Never print request objects/headers, credentials or raw provider responses.
            message = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
            errors.append(message)
            print(json.dumps({'workflow': 'NOT VERIFIED', 'error': message}), flush=True)
        finally:
            for client in (patient, doctor, unrelated):
                if client.cookies:
                    client.post('/api/v1/auth/logout')
    print(json.dumps({'live_erp_verified': not errors, 'errors': errors}), flush=True)
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
