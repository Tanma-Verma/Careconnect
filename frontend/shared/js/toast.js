let toastTimer;

export function toast(message) {
  const node = document.getElementById("toast");
  if (!node) return;
  node.textContent = message;
  node.style.opacity = "1";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    node.style.opacity = "0";
  }, 2600);
}
