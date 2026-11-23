"use strict";
const el = (id) => document.getElementById(id);
const languages = new Intl.DisplayNames(["tr"], { type: "language" });
const dates = new Intl.DateTimeFormat("tr-TR", {
  dateStyle: "medium",
  timeZone: "Europe/Istanbul",
});
let page = 1,
  pending = 0,
  publishers = [];
function node(tag, value, cls) {
  const n = document.createElement(tag);
  if (value) n.textContent = value;
  if (cls) n.className = cls;
  return n;
}
function language(code) {
  try {
    return languages.of(code) || code;
  } catch {
    return code;
  }
}
function link(title, url) {
  const a = node("a", title);
  a.href = url;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  return a;
}
function select(id, first, entries) {
  const field = el(id),
    saved = field.value;
  field.replaceChildren(
    new Option(first, ""),
    ...entries.map(([value, title]) => new Option(title, value)),
  );
  field.value = saved;
}
function article(row) {
  const item = node("article"),
    name = publishers.find((s) => s.host === row.host)?.name || row.host;
  const stamp = row.published
    ? dates.format(new Date(row.published))
    : "Yayın tarihi belirtilmedi";
  item.append(
    node("div", [name, language(row.lang), stamp].join(" · "), "byline"),
  );
  const title = node("h2", row.title_tr || row.title);
  if (!row.title_tr) title.lang = row.lang;
  item.append(title);
  if (row.excerpt_tr || row.excerpt) {
    const excerpt = node("p", row.excerpt_tr || row.excerpt);
    excerpt.lang = row.excerpt_tr ? "tr" : row.lang;
    item.append(excerpt);
  }
  if (!row.title_tr || (row.excerpt && !row.excerpt_tr))
    item.append(
      node(
        "p",
        row.original_only
          ? "Türkçesi doğrulanamayan bölüm özgün dilinde gösteriliyor."
          : "Özgün dil · " + language(row.lang),
        "byline",
      ),
    );
  if ((row.title_tr || row.excerpt_tr) && !row.lang.startsWith("tr")) {
    const details = node("details");
    details.append(node("summary", "Özgün başlık ve özet"));
    const original = node("p", row.title);
    original.lang = row.lang;
    details.append(original);
    if (row.excerpt) {
      const excerpt = node("p", row.excerpt);
      excerpt.lang = row.lang;
      details.append(excerpt);
    }
    item.append(details);
  }
  const local = node("a", "Arşivde oku");
  local.href = "/arsiv/oku/-" + row.revision;
  item.append(
    local,
    document.createTextNode(" · "),
    link("Kaynağında oku ↗", row.url),
  );
  if (row.versions > 1) {
    const history = node("details");
    history.append(node("summary", "Arşivdeki önceki kayıtlar"));
    history.addEventListener("toggle", async () => {
      if (!history.open || history.children.length > 1) return;
      try {
        const response = await fetch("/api/dis-basin/" + row.id + "/gecmis");
        if (!response.ok) throw Error();
        for (const r of await response.json()) {
          const box = node("p");
          box.append(
            node(
              "strong",
              dates.format(new Date(r.observed * 1000)) +
                " · " +
                (r.title_tr || r.title),
            ),
            node("br"),
            node("span", r.excerpt_tr || r.excerpt),
          );
          const archived = node("a", "Bu kaydı aç");
          archived.href = "/arsiv/oku/-" + r.revision;
          box.append(node("br"), archived);
          history.append(box);
        }
      } catch {
        history.append(node("p", "Kayıt geçmişi yüklenemedi."));
      }
    });
    item.append(history);
  }
  return item;
}
async function load() {
  const run = ++pending,
    params = new URLSearchParams({
      sayfa: page,
      kaynak: el("publisher").value,
      dil: el("language").value,
    });
  try {
    const response = await fetch("/api/dis-basin?" + params, {
      cache: "no-cache",
    });
    if (!response.ok) throw Error();
    const data = await response.json();
    if (run !== pending) return;
    publishers = data.sources;
    select(
      "publisher",
      "Tüm yayıncılar",
      publishers.map((s) => [s.host, s.name + " (" + s.articles + ")"]),
    );
    select(
      "language",
      "Tüm diller",
      data.languages.map((l) => [l, language(l)]),
    );
    el("stories").replaceChildren(...data.items.map(article));
    el("result").textContent = data.total
      ? data.total + " arşiv kaydı"
      : "Bu seçim için henüz haber yok.";
    el("last").textContent = data.checked
      ? "Son başarılı kontrol " + dates.format(new Date(data.checked * 1000))
      : "İlk tarama bekleniyor.";
    el("coverage").textContent = data.errors
      ? data.errors + " tarama yeniden denenecek. Alınan haberler arşivde."
      : data.checked_tasks < data.expected_tasks
        ? "İlk tarama sürüyor."
        : "Kaynaklar yedi günde bir taranır.";
    el("previous").disabled = page <= 1;
    el("next").disabled = page * 20 >= data.total;
    el("pagination").textContent =
      page + " / " + Math.max(1, Math.ceil(data.total / 20));
  } catch {
    if (run === pending)
      el("result").textContent =
        "Haber arşivine ulaşılamadı. Yenile ile tekrar dene.";
  }
}
let directory = [];
function showDirectory() {
  const query = el("source-search").value.toLocaleLowerCase("tr");
  const rows = directory.filter(
    (s) =>
      s.approved === Number(el("trust").value) &&
      (s.host + " " + s.name).toLocaleLowerCase("tr").includes(query),
  );
  el("sources").replaceChildren(
    ...rows.map((s) => {
      const div = node("div");
      div.append(
        node("strong", s.name),
        node("br"),
        node("span", s.host + " · "),
      );
      if (s.approved) div.append(link("Dayanak", s.evidence));
      else div.append(node("span", "Yayıma alınmadı"));
      return div;
    }),
  );
}
el("directory").ontoggle = async () => {
  if (!el("directory").open) return;
  try {
    const r = await fetch("/api/dis-basin/kaynaklar");
    if (!r.ok) throw Error();
    directory = await r.json();
    showDirectory();
  } catch {
    el("sources").textContent = "Kaynak listesi yüklenemedi.";
  }
};
el("source-search").oninput = el("trust").onchange = showDirectory;
el("publisher").onchange = el("language").onchange = () => {
  page = 1;
  load();
};
el("previous").onclick = () => {
  if (page > 1) {
    page--;
    load();
  }
};
el("next").onclick = () => {
  page++;
  load();
};
el("reload").onclick = load;
load();
setInterval(() => {
  if (!document.hidden && !document.querySelector("article details[open]"))
    load();
}, 90000);
