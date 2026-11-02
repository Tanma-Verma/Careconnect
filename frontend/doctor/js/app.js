import { api, AuthApi, resetRequests } from "../../shared/js/api.js";
import { clear, el, greeting, initials, setText, todayLabel } from "../../shared/js/dom.js";
import { toast } from "../../shared/js/toast.js";
const pages = {dashboard:"Dashboard",schedule:"Appointments",patients:"My patients",history:"Medical history",records:"Clinical notes",reports:"Medical reports",assistant:"AI assistant",audit:"Audit history",profile:"My profile"};
const $ = id => document.getElementById(id);
const prefix = "/api/v1/doctor";
let user = null, epoch = 0, chartEpoch = 0, selected = null, patients = [], appointments = [], chatBusy = false, noteBusy = false, authBusy = false;
const channel = typeof BroadcastChannel === "function" ? new BroadcastChannel("careconnect-session") : null;
const date = value => value ? new Date(value).toLocaleString() : "—";
const shortDate = value => value ? String(value).slice(0,10) : "—";
function formatAvailability(value) {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map(slot => typeof slot === "string" ? slot : [slot.day, slot.start && slot.end ? `${slot.start}–${slot.end}` : slot.start || slot.end, slot.timezone].filter(Boolean).join(" ")).join(" · ");
  return Object.entries(value || {}).map(([key, item]) => `${key.replaceAll("_", " ")}: ${Array.isArray(item) ? item.join(", ") : item}`).join(" · ");
}
const sourceUrl = (pid,did,page=null) => `${prefix}/patients/${encodeURIComponent(pid)}/documents/${encodeURIComponent(did)}/source${page ? `#page=${Number(page)}` : ""}`;
const path = suffix => `${prefix}/patients/${encodeURIComponent(selected.id)}${suffix}`;
const current = revision => Boolean(user && revision === epoch);
const chartCurrent = (revision,chart,id) => current(revision) && chart === chartEpoch && selected?.id === id;
function status(id,message,kind="empty") { $(id).hidden=!message; $(id).className=`status-banner ${kind}`; $(id).textContent=message; }
function loginError(message) { setText("loginError",message); $("loginError").classList.toggle("show",Boolean(message)); }
function emptyTable(id,cols,message) { clear($(id)); $(id).append(el("tr",{},[el("td",{colspan:cols,class:"muted",text:message})])); }
function closeMenu() { $("sidebar").classList.remove("open"); $("sidebarBackdrop").classList.remove("show"); $("sidebarBackdrop").hidden=true; }
function clearChart() {
  chartEpoch++; selected=null; chatBusy=false; noteBusy=false;
  for(const id of ["patientSummary","historyRows","notesRows","reportsRows","chatmessages"]) clear($(id));
  $("noteContent").value=""; $("chatInput").value=""; $("selectedPatient").value="";
  $("noteAppointment").replaceChildren(el("option",{value:"",text:"No linked appointment"}));
  $("chatSend").disabled=true; $("saveNote").disabled=true;
  for(const id of ["historyStatus","notesStatus","reportsStatus"]) status(id,"Select an assigned, consented patient.");
  setText("patientContext","No patient selected. The assistant never searches all patients."); setText("chatContext","Select a patient to begin.");
}
function clearPrivate() {
  epoch++; user=null; patients=[]; appointments=[]; clearChart();
  for(const id of ["patientsRows","appointmentRows","todayList","recentReports","auditRows","profileFields"]) clear($(id));
  $("selectedPatient").replaceChildren(el("option",{value:"",text:"Choose an assigned, consented patient"}));
  for(const id of ["statPatients","statToday","statUpcoming","statPending"]) setText(id,"—");
  for(const id of ["miniName","miniAvatar","topAvatar","welcomeTitle","profileName","profileMeta","profileAvatar"]) setText(id,"");
  for(const id of ["dashboardStatus","scheduleStatus","patientsStatus","auditStatus","profileStatus"]) status(id,"Sign in to view your workspace.");
  $("loginId").value=""; $("loginPass").value=""; $("patientSearch").value=""; loginError(""); closeMenu();
}
function showLogin(message="") { $("app").hidden=true; $("login").hidden=false; $("login").style.display="flex"; loginError(message); }
function expired() { resetRequests(); clearPrivate(); showLogin("Your session changed or expired. Sign in again."); }
window.addEventListener("session-expired",expired); channel?.addEventListener("message",expired);
function scopeError(error,target) {
  if([403,404].includes(error.status)) { clearChart(); setText("patientContext","Patient or consent scope unavailable. Refresh My patients to check access."); }
  status(target,error.message,"error");
}
function go(id,load=true) {
  if(!pages[id]) return;
  document.querySelectorAll(".page").forEach(page=>page.classList.toggle("active",page.id===id));
  document.querySelectorAll(".nav button[data-page]").forEach(button=>{const active=button.dataset.page===id;button.classList.toggle("active",active);if(active)button.setAttribute("aria-current","page");else button.removeAttribute("aria-current");});
  setText("crumb",pages[id]);closeMenu();history.replaceState(null,"",`#${id}`);
  if(load&&user) ({dashboard:loadDashboard,schedule:loadAppointments,patients:()=>loadPatients(),history:loadHistory,records:loadNotes,reports:loadReports,audit:loadAudit,profile:loadProfile}[id])?.();
}
function sourceLink(doc,pid) { return el("a",{class:"link",href:sourceUrl(pid,doc.id),target:"_blank",rel:"noopener",text:"View source"}); }
function appointmentCard(item) { return el("div",{class:"activity-row"},[el("div",{class:"file-ico",text:"▣"}),el("div",{},[el("b",{text:item.patient_name||"Assigned patient"}),el("small",{text:`${date(item.scheduled_at)} · ${item.reason}`})]),el("span",{class:"tag blue",text:item.status})]); }
async function loadDashboard() {
  const rev=epoch;status("dashboardStatus","Loading dashboard…","loading");clear($("todayList"));clear($("recentReports"));
  try {
    const result=await api(`${prefix}/dashboard`);if(!current(rev))return;
    for(const [id,key] of [["statPatients","assigned_patients"],["statToday","today_appointments"],["statUpcoming","upcoming_appointments"],["statPending","pending_tasks"]])setText(id,result.stats[key]);
    for(const item of result.appointments)$("todayList").append(appointmentCard(item));
    if(!result.appointments.length)$("todayList").append(el("p",{class:"sub",text:"No appointments available."}));
    for(const doc of result.documents)$("recentReports").append(el("div",{class:"record-row"},[el("div",{},[el("b",{text:doc.filename}),el("small",{text:`${doc.state} · ${shortDate(doc.created_at)}`})]),sourceLink(doc,doc.patient_id||doc.owner_id)]));
    if(!result.documents.length)$("recentReports").append(el("p",{class:"sub",text:"No authorized reports available."}));
    status("dashboardStatus","Current database statistics. Refresh your workspace after consent changes.");
  }catch(error){if(current(rev))status("dashboardStatus",error.message,"error");}
}
async function loadPatients(query="") {
  const rev=epoch;status("patientsStatus","Loading assigned, consented patients…","loading");emptyTable("patientsRows",4,"Loading patients…");
  try {
    const result=await api(`${prefix}/patients?q=${encodeURIComponent(query)}`);if(!current(rev))return;
    if(!query){patients=result.patients;$("selectedPatient").replaceChildren(el("option",{value:"",text:"Choose an assigned, consented patient"}));
      for(const patient of patients)$("selectedPatient").append(el("option",{value:patient.id,text:`${patient.name}${patient.is_demo?" · synthetic demo":""}`}));
      if(selected&&patients.some(p=>p.id===selected.id))$("selectedPatient").value=selected.id;else if(selected)clearChart();
    }
    clear($("patientsRows"));
    for(const patient of result.patients){const scopes=[patient.records&&"Records",patient.clinical&&"Clinical",patient.ai&&"AI"].filter(Boolean).join(" · ");
      $("patientsRows").append(el("tr",{},[el("td",{},[el("b",{text:patient.name}),el("small",{text:patient.is_demo?"Synthetic demonstration patient":""})]),el("td",{text:shortDate(patient.dob)}),el("td",{text:scopes}),el("td",{},[el("button",{class:"secondary",type:"button",text:"Open chart",onclick:()=>selectPatient(patient.id,patient)})])]));}
    if(!result.patients.length)emptyTable("patientsRows",4,"No matching assigned patients with record consent.");
    status("patientsStatus",`${result.patients.length} authorized patients${query?" matching your search":""}.`);
  }catch(error){if(current(rev))status("patientsStatus",error.message,"error");}
}
async function selectPatient(id,candidate=null) {
  clearChart();if(!id||!user)return;const rev=epoch,chart=chartEpoch;
  selected={id,name:candidate?.name||patients.find(p=>p.id===id)?.name||"Selected patient"};$("selectedPatient").value=id;setText("patientContext",`Opening ${selected.name}…`);
  try {
    const result=await api(path(""));if(!chartCurrent(rev,chart,id))return;
    selected={...result.patient,consent:result.consent};const label=`${selected.name}${selected.is_demo?" · synthetic demonstration patient":""}`;
    setText("patientContext",`Selected: ${label}. Access is rechecked for each operation.`);setText("chatContext",`Patient: ${label}${result.consent.ai?"":" · AI consent is not granted"}`);
    $("chatSend").disabled=!(result.consent.records&&result.consent.ai);$("saveNote").disabled=!result.consent.clinical;fillNoteAppointments();go(result.consent.clinical?"history":"reports");
  }catch(error){if(chartCurrent(rev,chart,id))scopeError(error,"historyStatus");}
}
function patientRequired(target) { if(selected)return false;status(target,"Select an assigned, consented patient using Patient chart context.");return true; }
function summaryRow(label,value) { return el("div",{class:"activity-row"},[el("b",{text:label}),el("span",{text:value})]); }
async function loadHistory() {
  clear($("historyRows"));clear($("patientSummary"));if(patientRequired("historyStatus"))return;
  const rev=epoch,chart=chartEpoch,id=selected.id;status("historyStatus","Loading selected patient's clinical history…","loading");
  try {
    const result=await api(path("/history"));if(!chartCurrent(rev,chart,id))return;
    $("patientSummary").append(summaryRow("Patient",selected.name),summaryRow("Date of birth",shortDate(selected.dob)),summaryRow("Demographic sex",selected.sex||"Not recorded"));
    for(const item of result.history||[])$("historyRows").append(el("div",{class:"activity-row"},[el("div",{},[el("b",{text:typeof item==="string"?item:item.condition||item.title||item.summary||item.description||"Clinical history"}),el("small",{text:typeof item==="string"?"":[item.date||item.recorded_at,item.details||item.note,item.status].filter(Boolean).join(" · ")})])]));
    const timeline=[...(result.observations||[]).map(item=>({time:item.measured_at,title:item.code,text:`${item.value} ${item.unit}${item.reference_low!=null&&item.reference_high!=null?` · reference ${item.reference_low}–${item.reference_high} ${item.unit}`:""}`})),...(result.notes||[]).map(item=>({time:item.created_at,title:`Clinical note · ${item.doctor_name||"Practitioner"}`,text:item.content})),...(result.documents||[]).map(item=>({time:item.created_at,title:item.filename,text:`Medical report · ${item.state}`}))].sort((a,b)=>new Date(b.time)-new Date(a.time));
    for(const item of timeline)$("historyRows").append(el("div",{class:"activity-row"},[el("div",{class:"file-ico",text:"▤"}),el("div",{},[el("b",{text:item.title}),el("small",{text:`${date(item.time)} · ${item.text}`})])]));
    status("historyStatus",timeline.length||result.history?.length?"Clinical history loaded. Notes are structured records, outside AI retrieval.":"No clinical history recorded.");
  }catch(error){if(chartCurrent(rev,chart,id))scopeError(error,"historyStatus");}
}
function fillNoteAppointments() {
  $("noteAppointment").replaceChildren(el("option",{value:"",text:"No linked appointment"}));
  for(const item of appointments.filter(item=>item.patient_id===selected?.id))$("noteAppointment").append(el("option",{value:item.id,text:`${date(item.scheduled_at)} · ${item.status}`}));
}
async function loadAppointments() {
  const rev=epoch;status("scheduleStatus","Loading appointments…","loading");emptyTable("appointmentRows",5,"Loading appointments…");
  try {
    const result=await api(`${prefix}/appointments`);if(!current(rev))return;appointments=result.appointments;fillNoteAppointments();clear($("appointmentRows"));
    for(const item of appointments){const actions=el("div");
      for(const next of item.status==="REQUESTED"?["CONFIRMED","CANCELLED"]:item.status==="CONFIRMED"?["COMPLETED","CANCELLED"]:[])actions.append(el("button",{class:"secondary",type:"button",text:next==="CANCELLED"?"Cancel":next==="CONFIRMED"?"Confirm":"Complete",onclick:event=>updateAppointment(item.id,next,event.currentTarget)}));
      $("appointmentRows").append(el("tr",{},[el("td",{text:item.patient_name||"Assigned patient"}),el("td",{text:date(item.scheduled_at)}),el("td",{text:item.reason}),el("td",{},[el("span",{class:"tag blue",text:item.status})]),el("td",{},[actions])]));}
    if(!appointments.length)emptyTable("appointmentRows",5,"No appointments available.");status("scheduleStatus",`${appointments.length} appointments. Status updates are checked by the backend.`);
  }catch(error){if(current(rev))status("scheduleStatus",error.message,"error");}
}
async function updateAppointment(id,next,button){const rev=epoch;button.disabled=true;
  try{await api(`${prefix}/appointments/${encodeURIComponent(id)}`,{method:"PATCH",body:{status:next}});if(current(rev))await Promise.all([loadAppointments(),loadDashboard()]);}
  catch(error){if(current(rev))status("scheduleStatus",error.message,"error");}finally{if(current(rev))button.disabled=false;}
}
async function loadNotes(){clear($("notesRows"));if(patientRequired("notesStatus"))return;const rev=epoch,chart=chartEpoch,id=selected.id;status("notesStatus","Loading clinical notes…","loading");
  try{const result=await api(path("/notes"));if(!chartCurrent(rev,chart,id))return;
    for(const item of result.notes)$("notesRows").append(el("div",{class:"activity-row"},[el("div",{},[el("b",{text:`${date(item.created_at)} · ${item.doctor_name||"Practitioner"}`}),el("p",{text:item.content})])]));
    status("notesStatus",result.notes.length?`${result.notes.length} clinical notes. These are not indexed by the AI assistant.`:"No notes recorded. Create the first note below.");
  }catch(error){if(chartCurrent(rev,chart,id))scopeError(error,"notesStatus");}
}
async function saveNote(event){event.preventDefault();if(!selected||noteBusy||!user)return;const content=$("noteContent").value.trim();if(!content)return status("notesStatus","Enter a clinical note.","error");
  const rev=epoch,chart=chartEpoch,id=selected.id;noteBusy=true;$("saveNote").disabled=true;status("notesStatus","Saving clinical note…","loading");
  try{const body={content};if($("noteAppointment").value)body.appointment_id=$("noteAppointment").value;await api(path("/notes"),{method:"POST",body});if(!chartCurrent(rev,chart,id))return;$("noteContent").value="";await loadNotes();}
  catch(error){if(chartCurrent(rev,chart,id))scopeError(error,"notesStatus");}finally{if(chartCurrent(rev,chart,id)){noteBusy=false;$("saveNote").disabled=!selected.consent?.clinical;}}
}
async function loadReports(){clear($("reportsRows"));if(patientRequired("reportsStatus"))return;const rev=epoch,chart=chartEpoch,id=selected.id;status("reportsStatus","Loading authorized reports…","loading");
  try{const result=await api(path("/documents"));if(!chartCurrent(rev,chart,id))return;
    for(const doc of result.documents)$("reportsRows").append(el("tr",{},[el("td",{text:doc.filename}),el("td",{text:date(doc.created_at)}),el("td",{},[el("span",{class:"tag blue",text:doc.state}),el("small",{text:doc.error||`${doc.chunk_count} indexed chunks`})]),el("td",{},[sourceLink(doc,id)])]));
    if(!result.documents.length)emptyTable("reportsRows",4,"No reports available.");status("reportsStatus",`${result.documents.length} reports. Only READY reports are searched by the assistant.`);
  }catch(error){if(chartCurrent(rev,chart,id))scopeError(error,"reportsStatus");}
}
function bubble(text,mine=false){const node=el("div",{class:mine?"bubble me":"bubble",text});$("chatmessages").append(node);$("chatmessages").scrollTop=$("chatmessages").scrollHeight;return node;}
async function sendChat(event){event.preventDefault();if(!selected||!user||chatBusy)return;const message=$("chatInput").value.trim();if(!message)return;
  const rev=epoch,chart=chartEpoch,id=selected.id;$("chatInput").value="";bubble(message,true);const pending=bubble(`Searching ${selected.name}'s authorized reports and preparing an answer…`);chatBusy=true;$("chatSend").disabled=true;
  try{const result=await api(path("/ai/chat"),{method:"POST",body:{message}});if(!chartCurrent(rev,chart,id))return;pending.remove();const answer=bubble(result.answer);
    for(const citation of result.citations)answer.append(el("details",{},[el("summary",{text:`[${citation.label}] ${citation.title}${citation.page?` · page ${citation.page}`:""}`}),el("p",{text:citation.excerpt}),el("a",{class:"link",href:sourceUrl(id,citation.document_id,citation.page),target:"_blank",rel:"noopener",text:"Open authorized source document"})]));
    answer.append(el("small",{class:"muted",text:`Request: ${result.request_id}`}));
  }catch(error){if(!chartCurrent(rev,chart,id))return;if([403,404].includes(error.status)){clearChart();setText("patientContext",`Access unavailable: ${error.message}`);}else pending.textContent=error.message;}
  finally{if(chartCurrent(rev,chart,id)){chatBusy=false;$("chatSend").disabled=!selected.consent?.ai;}}
}
async function loadAudit(){const rev=epoch;clear($("auditRows"));status("auditStatus","Loading access history…","loading");
  try{const result=await api("/api/v1/audit");if(!current(rev))return;for(const item of result.events)$("auditRows").append(el("div",{class:"activity-row"},[el("div",{},[el("b",{text:item.action}),el("small",{text:`${date(item.createdAt)} · ${item.outcome}`})])]));status("auditStatus",result.events.length?"":"No access events recorded.");}
  catch(error){if(current(rev))status("auditStatus",error.message,"error");}
}
async function loadProfile(){const rev=epoch;status("profileStatus","Loading practitioner profile…","loading");
  try{const {profile}=await api(`${prefix}/profile`);if(!current(rev))return;setText("profileName",profile.name);setText("miniName",profile.name);setText("welcomeTitle",`${greeting()}, ${profile.name}`);setText("profileMeta",`${profile.specialty} · ${profile.department}${profile.is_demo?" · Synthetic demonstration profile":""}`);clear($("profileFields"));
    const availability=formatAvailability(profile.availability);
    for(const [label,value]of[["Email",user.email],["Qualifications",profile.qualifications],["Experience",`${profile.experience} years`],["Availability",availability],["Profile",profile.bio]])$("profileFields").append(el("div",{},[el("span",{class:"sub",text:label}),el("b",{class:"profile-value",text:value||"Not recorded"})]));status("profileStatus","");
  }catch(error){if(current(rev))status("profileStatus",error.message,"error");}
}
async function afterAuth(account){if(account.role!=="PRACTITIONER"){try{await AuthApi.logout();}finally{resetRequests();clearPrivate();showLogin("A provisioned practitioner account is required. Patient accounts use /patient/.");}return;}
  user=account;setText("miniName",account.email);for(const id of["miniAvatar","topAvatar","profileAvatar"])setText(id,initials(account.email));setText("welcomeTitle",`${greeting()}, ${account.email.split("@")[0]}`);setText("topDate",todayLabel());setText("welcomeDate",todayLabel());$("login").hidden=true;$("login").style.display="none";$("app").hidden=false;const page=location.hash.slice(1);go(pages[page]?page:"dashboard",false);
  await Promise.all([loadDashboard(),loadPatients(),loadAppointments(),loadProfile(),loadAudit()]);
}
$("loginForm").addEventListener("submit",async event=>{event.preventDefault();if(authBusy)return;authBusy=true;loginError("");$("loginSubmit").disabled=true;
  const email=$("loginId").value.trim(),password=$("loginPass").value;resetRequests();clearPrivate();
  try{const result=await AuthApi.login(email,password);channel?.postMessage("account-changed");await afterAuth(result.user);}catch(error){loginError(error.message);}finally{authBusy=false;$("loginSubmit").disabled=false;}
});
$("logoutBtn").addEventListener("click",async()=>{authBusy=true;$("loginSubmit").disabled=true;resetRequests(true);clearPrivate();showLogin();channel?.postMessage("signed-out");try{await AuthApi.logout();}catch(error){loginError(`Local workspace data cleared. Server sign-out failed: ${error.message}`);}finally{resetRequests();authBusy=false;$("loginSubmit").disabled=false;}});
document.querySelectorAll(".nav button[data-page]").forEach(button=>button.addEventListener("click",()=>go(button.dataset.page)));
$("selectedPatient").addEventListener("change",event=>selectPatient(event.target.value));
$("patientSearchForm").addEventListener("submit",event=>{event.preventDefault();loadPatients($("patientSearch").value.trim());});
$("refreshPatients").addEventListener("click",()=>loadPatients());$("refreshAppointments").addEventListener("click",loadAppointments);$("refreshHistory").addEventListener("click",loadHistory);$("refreshReports").addEventListener("click",loadReports);$("refreshAudit").addEventListener("click",loadAudit);
$("noteForm").addEventListener("submit",saveNote);$("chatForm").addEventListener("submit",sendChat);
$("supportBtn").addEventListener("click",()=>toast("An active assignment and patient consent are required. Clinical records and AI have separate consent scopes."));
$("menuBtn").addEventListener("click",()=>{const open=$("sidebar").classList.toggle("open");$("sidebarBackdrop").hidden=!open;$("sidebarBackdrop").classList.toggle("show",open);});$("sidebarBackdrop").addEventListener("click",closeMenu);
(async function boot(){clearPrivate();try{const result=await AuthApi.me();await afterAuth(result.user);}catch{showLogin();}})();
