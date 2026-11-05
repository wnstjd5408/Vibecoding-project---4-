"use strict";
(() => {
  const get = id => document.getElementById(id);
  const slots = ["D01", "D02", "D03"];
  let bundle = null, busy = false, next = null, saved = null;
  function render() {
    get("bundle").disabled = busy;
    for (const id of ["preflight", "status"]) get(id).disabled = busy || !bundle;
    for (const id of slots) get(id).disabled = busy || !bundle || next !== id;
    get("download").disabled = busy || !saved;
  }
  get("bundle").onchange = async () => {
    if (busy) return;
    bundle = null; next = null; saved = null; busy = true; render();
    get("output").textContent = "";
    try {
      const file = get("bundle").files[0];
      if (!file || file.size > 2000000) throw new Error();
      const text = await file.text();
      const data = JSON.parse(text);
      if (!data.cases || !data.manifest || !data.config) throw new Error();
      bundle = text;
      get("notice").textContent = "파일 준비 완료. 무과금 사전 점검을 실행하세요.";
    } catch {
      get("notice").textContent = "요청 JSON을 확인하세요. 파일 상한은 2MB입니다.";
    } finally { busy = false; render(); }
  };
  async function submit(action) {
    if (busy || !bundle) return;
    if (action.startsWith("run/") && action !== "run/" + next) return;
    busy = true; next = null; saved = null; render();
    get("notice").textContent = "처리 중입니다. 자동 재시도하지 않습니다.";
    try {
      const response = await fetch("/api/internal/evals/" + action, {
        method: "POST", credentials: "same-origin", cache: "no-store", redirect: "error",
        headers: {"Content-Type": "application/json"}, body: bundle
      });
      const data = await response.json();
      get("output").textContent = JSON.stringify(data, null, 2);
      if (!response.ok) throw new Error();
      if (action === "preflight") {
        if (data.ready === true && slots.includes(data.next_slot)) next = data.next_slot;
        get("notice").textContent = next ? "사전 점검 통과. " + next + " 실행 가능." : "실행할 슬롯이 없습니다.";
      } else {
        saved = data;
        get("notice").textContent = "원장 결과를 확인하세요. 다음 호출 전 사전 점검을 다시 실행하세요.";
      }
    } catch {
      get("notice").textContent = "요청 실패 또는 결과 불명입니다. 재실행하지 말고 결과 조회·원장을 확인하세요.";
    } finally { busy = false; render(); }
  }
  get("preflight").onclick = () => submit("preflight");
  get("status").onclick = () => submit("status");
  for (const slot of slots) get(slot).onclick = () => submit("run/" + slot);
  get("download").onclick = () => {
    if (busy || !saved) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(saved, null, 2)], {type: "application/json"}));
    const anchor = document.createElement("a");
    anchor.href = url; anchor.download = "eval-state.json"; anchor.click();
    URL.revokeObjectURL(url);
  };
  render();
})();
