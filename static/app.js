"use strict";
const $ = (id) => document.getElementById(id);
const paths = {
  refresh:
    "M20 7v5h-5 M4 17v-5h5 M5.5 8a7.5 7.5 0 0 1 12.8-2L20 9 M4 15l1.7 3A7.5 7.5 0 0 0 18.5 16",
  shield: "M12 3l8 3v6c0 5-5 8-8 10-3-2-8-5-8-10V6z M8.5 12l2.2 2.2 4.8-5",
  branch:
    "M6 7v9 M7 16c6 0 10-2 10-8 M6 3a2 2 0 1 0 .01 0 M6 17a2 2 0 1 0 .01 0 M17 4a2 2 0 1 0 .01 0",
  puzzle:
    "M4 5h5a2.5 2.5 0 1 1 5 0h4v5a2.5 2.5 0 1 1 0 5v4h-5a2.5 2.5 0 1 0-5 0H4v-5a2.5 2.5 0 1 0 0-5z",
  layers: "M12 3l9 5-9 5-9-5z M3 12l9 5 9-5 M3 16l9 5 9-5",
  sliders: "M3 7h7m4 0h7M3 17h11m4 0h3 M10 4v6m6 4v6",
  calendar: "M4 6h16v15H4z M8 3v6m8-6v6M4 11h16",
  bell: "M5 16c2-2 2-4 2-7a5 5 0 0 1 10 0c0 3 0 5 2 7l1 2H4z M10 21h4",
  book: "M3 4c4-1 7 0 9 2 2-2 5-3 9-2v14c-4-1-7 0-9 2-2-2-5-3-9-2z M12 6v14",
  down: "m6 9 6 6 6-6",
  x: "M6 6l12 12M18 6L6 18",
  external: "M13 4h7v7m0-7-10 10 M10 5H4v15h15v-6",
  check: "m4 12 5 5L20 6",
};
function icon(name) {
  return (
    '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round"><path d="' +
    paths[name] +
    '"/></svg>'
  );
}
document
  .querySelectorAll("[data-icon]")
  .forEach((n) => (n.outerHTML = icon(n.dataset.icon)));
const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const fmtDate = (
  v,
  options = { day: "numeric", month: "short", year: "numeric" },
) =>
  v
    ? new Intl.DateTimeFormat("tr-TR", {
        timeZone: "Europe/Istanbul",
        ...options,
      }).format(new Date(v.length === 10 ? v + "T12:00:00Z" : v))
    : "";
const recent = (a, b) =>
  (b.date || "").localeCompare(a.date || "") ||
  (b.score || 0) - (a.score || 0) ||
  b.id.localeCompare(a.id, "en", { numeric: true });
const degree = (s) =>
  s == null
    ? "Belirtilmedi"
    : s >= 9
      ? "Kritik"
      : s >= 7
        ? "Yüksek"
        : s >= 4
          ? "Orta"
          : "Düşük";
const scoreClass = (s) =>
  s >= 9 ? "critical" : s >= 7 ? "high" : s >= 4 ? "mid" : "low";
const scoreTag = (i) =>
  i.score == null
    ? ""
    : '<span class="score ' +
      scoreClass(i.score) +
      '">' +
      degree(i.score) +
      " · " +
      esc(i.score.toFixed(1)) +
      "</span>";
const badge = (v, color = "") =>
  '<span class="badge ' + color + '">' + esc(v) + "</span>";
const fmtTitle = (i) => i.tr[i.title] || i.title;
const sourceLabels = {
  releases: "PostgreSQL",
  security: "PostgreSQL",
  notes: "PostgreSQL belgeleri",
  commitfest: "CommitFest",
  pgxn: "PGXN",
  contrib: "PostgreSQL belgeleri",
};
const empty = (msg) => '<p class="empty">' + esc(msg) + "</p>";
let dataset = { items: [], sources: [], meta: {} },
  byId = new Map(),
  visibleCves = 5,
  activeArchive = "",
  archiveFilter = "",
  loading = false;
let memory = { baseline: null, read: {} };
try {
  const value = JSON.parse(localStorage.getItem("pg-gundem-v1"));
  if (
    value &&
    typeof value.read === "object" &&
    value.read &&
    Number.isInteger(value.baseline)
  )
    memory = value;
} catch {}
function persist() {
  try {
    localStorage.setItem("pg-gundem-v1", JSON.stringify(memory));
  } catch {}
}
function sorted(kind) {
  return dataset.items.filter((i) => i.kind === kind).sort(recent);
}
function displayDay(i) {
  return i.date ? '<time class="date">' + esc(fmtDate(i.date)) + "</time>" : "";
}
function itemAttrs(i) {
  return 'type="button" data-item="' + esc(i.id) + '"';
}
function summary(i) {
  if (i.fixed_text) return i.fixed_text;
  if (i.tr[i.summary]) return i.tr[i.summary];
  if (i.kind === "release")
    return i.count != null
      ? i.count + " güvenlik açığı için düzeltmeler yayımlandı."
      : "Bu sürümün değişikliklerini ve geçiş notlarını inceleyin.";
  return i.summary || "";
}
function featured() {
  return sorted("release")[0];
}
function alerts() {
  const first = featured();
  return dataset.items
    .filter(
      (i) =>
        (i.id === first?.id ||
          (memory.baseline !== null && i.seq > memory.baseline)) &&
        memory.read[i.id] !== i.seq,
    )
    .sort(
      (a, b) =>
        Number(b.kind === "security" && b.score >= 9) -
          Number(a.kind === "security" && a.score >= 9) || recent(a, b),
    );
}
function renderNotice() {
  const list = alerts(),
    panel = $("notice");
  panel.hidden = !list.length;
  if (panel.hidden) return;
  const msg =
    list.length === 1 && list[0].kind === "release"
      ? "Son PostgreSQL sürüm duyurusu okunmayı bekliyor."
      : list.length + " yeni veya güncellenmiş kayıt okunmayı bekliyor.";
  panel.innerHTML =
    '<span class="notice-symbol">' +
    icon("bell") +
    "</span><div><strong>Yeni gelişmeler var</strong><p>" +
    msg +
    '</p></div><button id="see-alerts">İncele</button>';
  $("see-alerts").onclick = () =>
    list.length === 1 ? openItem(list[0].id) : openArchive("alerts");
}
function renderFeature() {
  const i = featured();
  $("feature").innerHTML = i
    ? '<article class="feature"><div class="feature-text"><div class="feature-top"><span class="eyebrow">Son sürüm bülteni</span></div><h3>' +
      esc(i.title) +
      "</h3><p>" +
      esc(
        i.count != null
          ? i.count + " güvenlik açığı için düzeltme yayımlandı."
          : "Yeni PostgreSQL sürümü yayımlandı.",
      ) +
      '</p><div class="chips">' +
      i.versions
        .map((v) => '<span class="chip">' + esc(v) + "</span>")
        .join("") +
      '</div><button class="feature-button" ' +
      itemAttrs(i) +
      ">" +
      icon("book") +
      " Bülteni oku</button></div></article>"
    : empty("Sürüm bülteni bekleniyor.");
  $("older-releases").innerHTML =
    sorted("release").length > 1
      ? '<button class="history" data-archive="releases">Önceki sürüm bültenleri</button>'
      : "";
}
function renderCves() {
  const major = $("version").value,
    level = $("severity").value,
    all = sorted("security");
  const majors = [
    ...new Set(all.flatMap((i) => i.matrix.map((r) => r.major))),
  ].sort((a, b) => b.localeCompare(a, "en", { numeric: true }));
  $("version").innerHTML =
    '<option value="">Tüm sürümler</option>' +
    majors
      .map(
        (v) =>
          '<option value="' + esc(v) + '">PostgreSQL ' + esc(v) + "</option>",
      )
      .join("");
  $("version").value = major;
  const items = all.filter(
    (i) =>
      (!major || i.matrix.some((r) => r.major === major)) &&
      (!level || degree(i.score) === level),
  );
  $("cve-count").textContent = items.length;
  $("cve-list").innerHTML =
    items
      .slice(0, visibleCves)
      .map(
        (i) =>
          '<button class="cve-row" ' +
          itemAttrs(i) +
          '><span class="cve-top"><span class="number">' +
          esc(i.id) +
          "</span>" +
          scoreTag(i) +
          displayDay(i) +
          "</span><h4>" +
          esc(fmtTitle(i)) +
          "</h4><small>Etkilenen ana sürümler · " +
          esc(i.matrix.map((r) => r.major).join(", ")) +
          "</small></button>",
      )
      .join("") ||
    empty(
      all.length
        ? "Bu filtrelere uyan güvenlik kaydı yok."
        : "Güvenlik kayıtları bekleniyor.",
    );
  $("more-cves").hidden = items.length <= visibleCves;
}
function sideRow(i) {
  const text = summary(i),
    dev = i.kind === "dev";
  return (
    '<button class="side-row" ' +
    itemAttrs(i) +
    '><span class="side-meta">' +
    badge(i.label, dev ? "teal" : "purple") +
    displayDay(i) +
    "</span><h4>" +
    esc(fmtTitle(i)) +
    (!dev ? '<span class="version-tag">' + esc(i.version) + "</span>" : "") +
    "</h4>" +
    (text && text !== fmtTitle(i)
      ? '<p class="side-desc">' + esc(text) + "</p>"
      : "") +
    "</button>"
  );
}
function renderSides() {
  const dev = sorted("dev");
  const highlights = [
    dev.find((i) => i.source === "releases"),
    dev.find((i) => i.source === "notes"),
    dev.find((i) => i.source === "commitfest"),
  ].filter(Boolean);
  $("dev-list").innerHTML =
    highlights.map(sideRow).join("") ||
    empty("Geliştirme haberleri bekleniyor.");
  $("ext-list").innerHTML =
    sorted("extension").slice(0, 3).map(sideRow).join("") ||
    empty("Eklenti yayınları bekleniyor.");
}
function render() {
  byId = new Map(dataset.items.map((i) => [i.id, i]));
  if (
    memory.baseline === null &&
    dataset.meta.completed &&
    dataset.items.length
  ) {
    memory.baseline = Math.max(...dataset.items.map((i) => i.seq));
    persist();
  }
  const failed = dataset.sources.filter((s) => s.error);
  const completed = dataset.meta.completed,
    ready = completed && !failed.length;
  $("connection").className =
    "connection " + (failed.length ? "warn" : ready ? "ok" : "");
  $("connection").lastElementChild.textContent = failed.length
    ? "Kısmi bağlantı"
    : ready
      ? "Saatlik takip etkin"
      : "Kaynaklar taranıyor";
  $("health").hidden = !failed.length;
  $("health").textContent = failed.length
    ? failed
        .map(
          (s) =>
            s.label +
            " · " +
            (s.success
              ? "son başarılı kontrol " +
                fmtDate(s.success, {
                  day: "numeric",
                  month: "short",
                  hour: "2-digit",
                  minute: "2-digit",
                })
              : "ilk bağlantı bekleniyor"),
        )
        .join(" / ")
    : "";
  $("last-check").textContent = completed
    ? "Son kontrol " +
      fmtDate(completed, {
        day: "numeric",
        month: "long",
        hour: "2-digit",
        minute: "2-digit",
      }) +
      " · Türkiye saati"
    : "İlk kaynak kontrolü sürüyor";
  renderNotice();
  renderFeature();
  renderCves();
  renderSides();
}
function table(headers, rows) {
  return (
    '<div class="table-wrap"><table><thead><tr>' +
    headers.map((h) => '<th scope="col">' + esc(h) + "</th>").join("") +
    "</tr></thead><tbody>" +
    rows
      .map(
        (row) =>
          "<tr>" + row.map((v) => "<td>" + esc(v) + "</td>").join("") + "</tr>",
      )
      .join("") +
    "</tbody></table></div>"
  );
}
function official(i) {
  return (
    '<a class="source" target="_blank" rel="noopener noreferrer" href="' +
    esc(i.url) +
    '">' +
    esc(sourceLabels[i.source] || "Kaynak") +
    " kaynağını aç " +
    icon("external") +
    "</a>"
  );
}
function translated(i, s) {
  const original =
    '<details><summary>Özgün metin (İngilizce)</summary><p lang="en">' +
    esc(s) +
    "</p></details>";
  if (i.tr[s]) {
    return (
      esc(i.tr[s]) + (["security", "release"].includes(i.kind) ? original : "")
    );
  }
  const label = i.original_only?.includes(s)
    ? "Türkçe çeviri doğrulanamadı. Özgün metin (İngilizce)"
    : "Özgün metin (İngilizce)";
  return (
    '<span class="muted">' + label + '</span><p lang="en">' + esc(s) + "</p>"
  );
}
function show(content) {
  $("dialog-body").innerHTML = content;
  if (!$("reader").open) $("reader").showModal();
  $("reader").scrollTop = 0;
}
function openItem(id) {
  const i = byId.get(id);
  if (!i) return;
  let html =
    '<div class="detail-meta">' +
    badge(
      i.label ||
        { release: "Sürüm bülteni", security: "Güvenlik kaydı" }[i.kind] ||
        "",
      "blue",
    ) +
    displayDay(i) +
    scoreTag(i) +
    '</div><h2 id="dialog-title">' +
    esc(fmtTitle(i)) +
    "</h2>";
  if (i.kind === "security") {
    html +=
      '<div class="number">' +
      esc(i.id) +
      " · " +
      esc(
        {
          "core server": "PostgreSQL sunucusu",
          "contrib module": "Ek modül",
          client: "İstemci",
        }[i.component] || i.component,
      ) +
      "</div>";
    html +=
      "<h3>Etkisi</h3><div>" +
      translated(i, i.summary) +
      "</div><h3>Hangi sürüme geçmeliyim?</h3>";
    html += table(
      ["Etkilenen seri", "İlk düzeltme", "Güncel bakım sürümü"],
      i.matrix.map((r) => {
        const v = dataset.meta.versions?.[r.major];
        return [
          r.major,
          r.fixed || "Belirtilmedi",
          v ? (v.supported ? v.latest : "Destek sona erdi") : "Kaynağa bakın",
        ];
      }),
    );
    if (i.scope.length)
      html +=
        "<h3>Etkilenen sürüm aralığı</h3>" +
        i.scope.map((s) => "<div>" + translated(i, s) + "</div>").join("");
    const bulletin = byId.get(i.bulletin);
    if (
      i.matrix.some(
        (r) => dataset.meta.versions?.[r.major]?.supported === false,
      )
    )
      html +=
        '<p class="muted">Desteği sona eren bir seri kullanıyorsanız güvenlik güncellemelerini almaya devam etmek için desteklenen bir ana sürüme geçiş planlayın.</p>';
    if (i.extra || bulletin?.notes?.length)
      html +=
        '<div class="callout">' +
        (i.extra
          ? "Bu açık için ek düzeltme adımları var. Resmî güvenlik kaydındaki talimatları inceleyin."
          : "Bu sürüm bülteninde bazı kurulumlar için güncelleme sonrası ek işlemler var.") +
        "</div>";
    if (i.notes?.length)
      html +=
        "<h3>Bu açık için ek işlemler</h3><ol>" +
        i.notes.map((s) => "<li>" + translated(i, s) + "</li>").join("") +
        "</ol>";
    if (bulletin)
      html +=
        '<button class="refresh" ' +
        itemAttrs(bulletin) +
        ">İlgili yama bültenini oku</button>";
  } else {
    if (i.version || i.series)
      html +=
        '<p class="meta">' +
        esc(i.version || "PostgreSQL " + i.series) +
        "</p>";
    if (i.fixed_text) html += "<p>" + esc(i.fixed_text) + "</p>";
    else if (i.summary) html += "<div>" + translated(i, i.summary) + "</div>";
    if (i.meeting)
      html +=
        '<p class="muted">' +
        esc(i.meeting) +
        " dönemindeki önerinin durumu: " +
        esc(i.label) +
        ".</p>";
    if (i.versions) {
      html +=
        "<h3>Yayımlanan sürümler</h3>" +
        table(
          ["Ana sürüm", "Bu bültendeki sürüm", "Destek durumu"],
          i.versions.map((v) => {
            const key = v.includes(".") ? v.slice(0, v.lastIndexOf(".")) : v,
              info = dataset.meta.versions?.[key];
            return [
              key,
              v,
              info
                ? info.supported
                  ? "Destekleniyor"
                  : "Destek sona erdi"
                : "Kaynağa bakın",
            ];
          }),
        );
    }
    if (i.notes?.length)
      html +=
        "<h3>" +
        (i.kind === "release"
          ? "Güncelleme sonrası işlemler"
          : "Bu sürümdeki değişiklikler") +
        "</h3><ul>" +
        i.notes.map((s) => "<li>" + translated(i, s) + "</li>").join("") +
        "</ul>";
    else if (i.kind === "extension" && i.source === "pgxn")
      html +=
        '<p class="muted">Bu sürüm için ayrıntılı değişiklik bilgisi kaynak sayfasından incelenebilir.</p>';
  }
  html += '<div class="reader-actions">' + official(i) + "</div>";
  if (i.notes_url)
    html +=
      '<a class="source" target="_blank" rel="noopener noreferrer" href="' +
      esc(i.notes_url) +
      '">Sürüm notlarını aç ' +
      icon("external") +
      "</a>";
  if (activeArchive)
    html += '<button class="history" data-back="1">Listeye dön</button>';
  show(html);
  memory.read[id] = i.seq;
  persist();
  renderNotice();
}
const names = {
  alerts: "Yeni gelişmeler",
  dev: "Geliştirme arşivi",
  ext: "Eklenti arşivi",
  releases: "Sürüm bültenleri",
};
const options = {
  dev: [
    ["", "Tümü"],
    ["releases", "Beta ve RC"],
    ["notes", "Sürüm notları"],
    ["commitfest", "CommitFest"],
  ],
  ext: [
    ["", "Tümü"],
    ["pgxn", "PGXN"],
    ["contrib", "PostgreSQL ile gelenler"],
  ],
};
function openArchive(kind, filter = "") {
  activeArchive = kind;
  archiveFilter = filter;
  const list =
    kind === "alerts"
      ? alerts()
      : sorted(
          { dev: "dev", ext: "extension", releases: "release" }[kind],
        ).filter((i) => !filter || i.source === filter);
  const controls = (options[kind] || [])
    .map(
      ([v, label]) =>
        '<button data-filter="' +
        v +
        '" aria-pressed="' +
        (v === filter) +
        '">' +
        label +
        "</button>",
    )
    .join("");
  const allRead =
    kind === "alerts" && list.length
      ? '<button class="refresh" id="all-read">' +
        icon("check") +
        " Tümünü okundu işaretle</button>"
      : "";
  show(
    '<h2 id="dialog-title">' +
      names[kind] +
      '</h2><div class="archive-controls">' +
      controls +
      "</div>" +
      allRead +
      (list
        .map(
          (i) =>
            '<button class="archive-row" ' +
            itemAttrs(i) +
            '><span class="detail-meta">' +
            badge(i.label || sourceLabels[i.source]) +
            displayDay(i) +
            scoreTag(i) +
            "</span><h4>" +
            esc(fmtTitle(i)) +
            (i.version ? " · " + esc(i.version) : "") +
            "</h4></button>",
        )
        .join("") || empty("Gösterilecek kayıt yok.")),
  );
  if ($("all-read"))
    $("all-read").onclick = () => {
      list.forEach((i) => (memory.read[i.id] = i.seq));
      persist();
      renderNotice();
      $("reader").close();
    };
}
async function load() {
  if (loading) return;
  loading = true;
  $("refresh").disabled = true;
  try {
    const res = await fetch("/api/bulletin", {
      cache: "no-cache",
      signal: AbortSignal.timeout(15000),
    });
    if (!res.ok) throw Error("HTTP " + res.status);
    dataset = await res.json();
    render();
  } catch {
    $("health").hidden = false;
    $("health").textContent = "Panele ulaşılamadı. Bağlantı yeniden denenecek.";
    $("connection").className = "connection warn";
    $("connection").lastElementChild.textContent = "Bağlantı kesildi";
  } finally {
    loading = false;
    $("refresh").disabled = false;
  }
}
document.addEventListener("click", (e) => {
  const n = e.target.closest(
    "[data-item],[data-filter],[data-back],[data-archive],[data-nav]",
  );
  if (!n) return;
  if (n.dataset.item) openItem(n.dataset.item);
  else if (n.hasAttribute("data-filter"))
    openArchive(activeArchive, n.dataset.filter);
  else if (n.dataset.back) openArchive(activeArchive, archiveFilter);
  else if (n.dataset.archive) openArchive(n.dataset.archive);
  else if (n.dataset.nav)
    document
      .querySelectorAll("[data-nav]")
      .forEach((a) => a.classList.toggle("active", a === n));
});
$("refresh").onclick = load;
$("version").onchange = $("severity").onchange = () => {
  visibleCves = 5;
  renderCves();
};
$("more-cves").onclick = () => {
  visibleCves += 10;
  renderCves();
};
$("all-dev").onclick = () => openArchive("dev");
$("all-ext").onclick = () => openArchive("ext");
$("close").onclick = () => $("reader").close();
$("reader").addEventListener("close", () => {
  activeArchive = "";
  archiveFilter = "";
});
$("reader").addEventListener("click", (e) => {
  if (e.target === $("reader")) {
    const r = $("reader").getBoundingClientRect();
    if (
      e.clientX < r.left ||
      e.clientX > r.right ||
      e.clientY < r.top ||
      e.clientY > r.bottom
    )
      $("reader").close();
  }
});
window.addEventListener("storage", (e) => {
  if (e.key === "pg-gundem-v1" && e.newValue) {
    try {
      const m = JSON.parse(e.newValue);
      if (m.read) {
        memory = m;
        renderNotice();
      }
    } catch {}
  }
});
function stamp() {
  $("today").innerHTML =
    icon("calendar") +
    " " +
    esc(
      fmtDate(new Date().toISOString(), {
        weekday: "long",
        day: "numeric",
        month: "long",
        year: "numeric",
      }),
    );
}
stamp();
load();
setInterval(() => {
  stamp();
  if (!document.hidden) load();
}, 30000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) load();
});
