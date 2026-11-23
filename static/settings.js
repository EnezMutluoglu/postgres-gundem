"use strict";
const el = id => document.getElementById(id);
let csrf = "", available = "", poll;
async function api(path, body) {
  const res = await fetch("/api/admin/" + path, body === undefined ? {cache:"no-store"} : {
    method:"POST", headers:{"Content-Type":"application/json","X-CSRF-Token":csrf}, body:JSON.stringify(body)
  });
  if (!res.ok) {
    if (res.status === 401 && path !== "login") { clearInterval(poll); el("dashboard").hidden = true; el("login").hidden = false; }
    throw Error(({401:"Oturum açın veya parolanızı kontrol edin.",403:"Sayfayı yenileyip tekrar deneyin.",409:"Sürüm bilgisi değişti. Yeniden denetleyin.",429:"Çok sayıda giriş denemesi. Bir dakika sonra deneyin.",503:"Yönetim hizmeti hazır değil."})[res.status] || "İstek tamamlanamadı.");
  }
  return res.json();
}
function display(id, rows) {
  const list=el(id); list.replaceChildren();
  for(const [key,value] of rows) { const dt=document.createElement("dt"),dd=document.createElement("dd"); dt.textContent=key; dd.textContent=value ?? "Bekleniyor"; list.append(dt,dd); }
}
const date = x => x ? new Date(x).toLocaleString("tr-TR") : null;
async function refresh() {
  const s=await api("status"), r=s.release;
  display("health-list",[["Panel","Çalışıyor"],["SQLite",s.database ? "Hazır":"Hata"],["Yerel model",s.model?"Hazır":"Yanıt bekleniyor"],["Son başarılı tarama",date(s.last_scan)],["Çeviri bekleyen metin",s.pending],["Son çeviri hatası",s.translation_error ? date(s.translation_error.time)+" · "+s.translation_error.message : "Kayıt yok"],["Son aylık arşiv",s.archive],["Boş disk",(s.free/2**30).toFixed(1)+" GiB"]]);
  display("release-list",[["Kurulu sürüm",s.version],["Sunucu",r.platform],["Yeni sürüm",r.available || "—"],["İndirme üst sınırı",r.bytes ? (r.bytes/2**20).toFixed(0)+" MiB":"—"],["Son denetim",date(r.checked)],["İşlem",r.message]]);
  el("notes").textContent=r.notes || ""; available=r.available || ""; el("apply").hidden=!available || r.busy;
}
function report(err) { el("feedback").textContent=err.message; }
async function openPanel(){el("login").hidden=true;el("dashboard").hidden=false;await refresh();clearInterval(poll);poll=setInterval(()=>refresh().catch(report),10000);}
el("login").onsubmit=async e=>{e.preventDefault();try{const v=await api("login",{password:el("password").value});csrf=v.csrf;el("password").value="";el("feedback").textContent="";await openPanel();}catch(err){report(err);}};
el("logout").onclick=()=>api("logout",{}).then(()=>location.reload()).catch(report);
for(const action of ["check","apply"]) el(action).onclick=async()=>{const button=el(action);if(action==="apply" && !confirm(available+" sürümü kurulsun mu? Geçişte panel kısa süre yeniden başlatılır.")) return;button.disabled=true;try{await api(action,{version:available});el("feedback").textContent="İstek alındı.";await refresh();}catch(err){report(err);}finally{button.disabled=false;}};
api("session").then(s=>{csrf=s.csrf;if(s.authenticated)return openPanel();el("login").hidden=false;}).catch(report);
