/* Клиентская часть: запуск рекомендательных запросов (POST /api/recommend/{id}) и отрисовка
   результата карточками по полю `card` из заголовка .rq. */
(function () {
    "use strict";

    const NUM = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 });
    const PRICE = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });

    // шкала «звёзд» для оценок с маленьким максимумом; остальные score 0–100 — полоса
    const STAR_MAX = { "совпадение": 3, "похожесть": 2 };
    const SCORE_SUFFIX = { "упражнений": (v) => `нужен для ${v} упр.` };

    const EMPTY = {
        exercises_for_patient: "Подходящих упражнений не найдено — все кандидаты противопоказаны или слишком сложны. Стоит обсудить программу со специалистом.",
        exercises_for_diagnosis: "Для этого диагноза в базе знаний пока нет рекомендованных упражнений.",
        program_for_patient: "Готовой программы-шаблона для этого пациента не нашлось — программу нужно составить с нуля.",
        specialist_for_patient: "Нет специалистов, которые работают с диагнозом этого пациента.",
        equipment_for_patient: "Для этого пациента подходящего инвентаря не требуется — упражнения без снаряжения (или всё дороже бюджета).",
        replace_exercise: "Заменять нечего: у пациента нет назначенной программы или все её упражнения ему подходят.",
        audit_programs: "Все программы в порядке — проблем не найдено.",
        similar_patients: "Похожих пациентов с назначенными программами не найдено.",
        schedule_for_patient: "Нет программ с целью того же вида — рекомендовать длительность не по чему.",
        top_exercises_for_goal: "Для этой цели пока нет упражнений.",
        waiting_list: "Всем пациентам уже подобрана программа.",
    };
    const EMPTY_DEFAULT = "По заданным параметрам ничего не найдено.";

    // ------------------------------------------------------------ форматирование
    function esc(s) {
        return String(s).replace(/[&<>"']/g, (c) =>
            ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    }

    // средняяЭффективность → «Средняя эффективность»
    function humanize(col) {
        const s = col.replace(/([а-яёa-z0-9])([А-ЯЁA-Z])/g, "$1 $2").toLowerCase();
        return s.charAt(0).toUpperCase() + s.slice(1);
    }

    function isEmpty(v) {
        return v === null || v === undefined || v === "";
    }

    function formatValue(col, v) {
        if (isEmpty(v)) return "—";
        if (typeof v === "boolean") return v ? "Да" : "Нет";
        if (typeof v === "number") {
            const c = col.toLowerCase();
            if (c === "цена") return PRICE.format(v) + " ₽";
            if (c.includes("эффективность")) return NUM.format(v) + " %";
            if (c === "безопасность") return NUM.format(v) + " из 5";
            if (c.startsWith("сложность")) return NUM.format(v) + " из 4";
            return NUM.format(v);
        }
        return String(v);
    }

    function patientLink(row, iriCols) {
        for (const c of iriCols || []) {
            const v = row[c];
            if (typeof v !== "string") continue;
            if (v.startsWith("Пациент_")) return "/patients/" + encodeURIComponent(v);
            if (v.startsWith("Упр_")) return "/catalog?tab=exercises#" + encodeURIComponent(v);
            if (v.startsWith("Программа_")) return "/catalog?tab=programs#" + encodeURIComponent(v);
            if (v.startsWith("Реабилитолог_") || v.startsWith("Тренер_"))
                return "/catalog?tab=specialists#" + encodeURIComponent(v);
            return "/catalog?tab=equipment#" + encodeURIComponent(v);
        }
        return null;
    }

    // ------------------------------------------------------------ карточка результата
    function renderScore(col, v) {
        if (isEmpty(v)) return "";
        const label = esc(humanize(col));
        if (STAR_MAX[col]) {
            const max = STAR_MAX[col];
            const n = Math.max(0, Math.min(max, Math.round(v)));
            return `<div class="score stars" title="${label}">
                <span class="star-row">${"★".repeat(n)}<span class="off">${"★".repeat(max - n)}</span></span>
                <span class="score-text">${label}: ${n} из ${max}</span></div>`;
        }
        if (SCORE_SUFFIX[col]) {
            return `<div class="score"><span class="score-big">${esc(SCORE_SUFFIX[col](NUM.format(v)))}</span></div>`;
        }
        if (typeof v === "number" && v >= 0 && v <= 100) {
            return `<div class="score" title="${label}">
                <div class="score-bar"><div class="score-fill" style="width:${v}%"></div>
                <span>${label}: ${esc(NUM.format(v))}</span></div></div>`;
        }
        return `<div class="score"><span class="score-big">${esc(formatValue(col, v))}</span> <span class="muted">${label}</span></div>`;
    }

    function renderWarn(col, v) {
        if (isEmpty(v) || v === 0 || v === "0" || v === false) return "";
        const text = typeof v === "number" ? `${humanize(col)}: ${NUM.format(v)}` : String(v);
        return `<div class="warn-plate">⚠ ${esc(text)}</div>`;
    }

    function renderCard(meta, row, data) {
        const card = meta.card || {};
        const titleCol = card.title || data.columns.find((c) => !data.iri_columns.includes(c));
        const title = isEmpty(row[titleCol]) ? "—" : String(row[titleCol]);
        const href = patientLink(row, data.iri_columns);
        const warn = card.warn ? renderWarn(card.warn, row[card.warn]) : "";
        const tag = card.tag && !isEmpty(row[card.tag]) ? `<span class="badge badge-danger">${esc(row[card.tag])}</span>` : "";
        const fields = (card.fields || []).map((f) => {
            const val = row[f];
            return `<div class="kv"><span>${esc(humanize(f))}</span><b class="${isEmpty(val) ? "muted" : ""}">${esc(formatValue(f, val))}</b></div>`;
        }).join("");
        return `<article class="card result-card${warn ? " has-warn" : ""}">
            <div class="rc-head"><h3>${href ? `<a href="${href}">${esc(title)}</a>` : esc(title)}</h3>${tag}</div>
            ${card.score ? renderScore(card.score, row[card.score]) : ""}
            ${warn}
            <div class="fields">${fields}</div>
        </article>`;
    }

    function renderTable(meta, data) {
        const cols = data.columns.filter((c) => !data.iri_columns.includes(c));
        const head = cols.map((c) => `<th>${esc(humanize(c))}</th>`).join("");
        const warnCol = (meta.card || {}).warn;
        const body = data.rows.map((r) => {
            const warn = warnCol && !isEmpty(r[warnCol]) && r[warnCol] !== 0;
            return `<tr class="${warn ? "warn" : ""}">${cols.map((c) => `<td>${esc(formatValue(c, r[c]))}</td>`).join("")}</tr>`;
        }).join("");
        return `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
    }

    function paramSummary(meta, params) {
        return meta.params.map((p) => {
            const raw = params[p.name] ?? p.default;
            const opt = (p.options || []).find((o) => o.id === raw);
            const shown = opt ? opt.label : (p.type === "number" ? `${raw}` : raw);
            return `${p.name}: <b>${esc(shown)}</b>`;
        }).join(" · ");
    }

    function renderResult(meta, data, params, view) {
        const summary = meta.params.length ? `<div class="result-params">${paramSummary(meta, params)}</div>` : "";
        let body;
        if ("answer" in data) {
            body = data.answer
                ? `<div class="ask ask-yes"><span class="ask-big">✔ Можно</span><span>Упражнение подходит пациенту</span></div>`
                : `<div class="ask ask-no"><span class="ask-big">✖ Нельзя</span><span>Упражнение не подходит: не показано, противопоказано, слишком сложно или испытание приостановлено</span></div>`;
        } else if (!data.rows.length) {
            body = `<div class="empty">${esc(EMPTY[meta.id] || EMPTY_DEFAULT)}</div>`;
        } else if (view === "table") {
            body = renderTable(meta, data);
        } else {
            body = `<div class="cards">${data.rows.map((r) => renderCard(meta, r, data)).join("")}</div>`;
        }
        const count = "rows" in data ? `<span class="count">Найдено: ${data.rows.length}</span>` : "";
        return `<section class="result-block" data-result="${esc(meta.id)}">
            <div class="result-head"><h2>${esc(meta.icon)} ${esc(meta.title)}</h2>${count}</div>
            ${summary}
            <p class="muted description">${esc(meta.description)}</p>
            ${body}
        </section>`;
    }

    function renderError(meta, message) {
        return `<section class="result-block" data-result="${esc(meta.id)}">
            <div class="result-head"><h2>${esc(meta.icon)} ${esc(meta.title)}</h2></div>
            <div class="error-plate">Ошибка: ${esc(message)}</div></section>`;
    }

    // ------------------------------------------------------------ API
    async function recommend(id, params) {
        const resp = await fetch(`/api/recommend/${encodeURIComponent(id)}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ params }),
        });
        let data = null;
        try { data = await resp.json(); } catch (e) { /* не JSON */ }
        if (!resp.ok) {
            const detail = data && data.detail;
            throw new Error(typeof detail === "string" ? detail : `сервер ответил ${resp.status}`);
        }
        return data;
    }

    function loadQueries() {
        const el = document.getElementById("queries-data");
        return el ? JSON.parse(el.textContent) : [];
    }

    // ------------------------------------------------------------ страница пациента
    function initPatientPage(patientId, patientParam) {
        const queries = Object.fromEntries(loadQueries().map((q) => [q.id, q]));
        const results = document.getElementById("results");

        async function run(panel) {
            const meta = queries[panel.dataset.query];
            const btn = panel.querySelector(".run-btn");
            const params = { [patientParam]: patientId };
            panel.querySelectorAll("[data-param]").forEach((el) => { params[el.dataset.param] = el.value; });
            btn.disabled = true;
            btn.classList.add("loading");
            let html;
            try {
                html = renderResult(meta, await recommend(meta.id, params), params, "cards");
            } catch (e) {
                html = renderError(meta, e.message);
            } finally {
                btn.disabled = false;
                btn.classList.remove("loading");
            }
            const old = results.querySelector(`[data-result="${CSS.escape(meta.id)}"]`);
            const tmp = document.createElement("div");
            tmp.innerHTML = html;
            const block = tmp.firstElementChild;
            if (old) old.replaceWith(block); else results.prepend(block);
            return block;
        }

        document.querySelectorAll(".action[data-query]").forEach((panel) => {
            panel.querySelector(".run-btn").addEventListener("click", async () => {
                const block = await run(panel);
                block.scrollIntoView({ behavior: "smooth", block: "start" });
            });
        });
        document.getElementById("run-all").addEventListener("click", async () => {
            const panels = Array.from(document.querySelectorAll(".action[data-query]")).reverse();
            for (const p of panels) await run(p);
        });
        document.getElementById("clear-results").addEventListener("click", () => { results.innerHTML = ""; });
    }

    // ------------------------------------------------------------ страница «Рекомендации»
    function initRecommendPage() {
        const list = loadQueries();
        const queries = Object.fromEntries(list.map((q) => [q.id, q]));
        const select = document.getElementById("query-select");
        const fields = document.getElementById("param-fields");
        const description = document.getElementById("query-description");
        const runBtn = document.getElementById("run-btn");
        const results = document.getElementById("results");
        const url = new URL(window.location.href);
        let view = "cards";
        let last = null;

        function buildForm(meta, initial) {
            fields.innerHTML = meta.params.length ? "" : `<div class="field muted no-params">Параметров нет</div>`;
            for (const p of meta.params) {
                const value = initial[p.name] ?? p.default;
                const wrap = document.createElement("div");
                wrap.className = "field";
                const id = `param-${p.name}`;
                let control;
                if (p.type === "individual") {
                    control = `<select id="${esc(id)}" name="${esc(p.name)}">${p.options.map((o) =>
                        `<option value="${esc(o.id)}"${o.id === value ? " selected" : ""}>${esc(o.label)}</option>`).join("")}</select>`;
                } else {
                    control = `<input id="${esc(id)}" name="${esc(p.name)}" type="number" step="any" min="0" value="${esc(value)}" required>`;
                }
                const showClass = p.class && p.class.toLowerCase() !== p.name.toLowerCase();
                wrap.innerHTML = `<label for="${esc(id)}">${esc(humanize(p.name))}${showClass ? ` <span class="muted">(${esc(p.class)})</span>` : ""}</label>${control}`;
                fields.appendChild(wrap);
            }
            description.textContent = meta.description;
            runBtn.textContent = meta.button;
        }

        function currentParams(meta) {
            const params = {};
            for (const p of meta.params) {
                const el = fields.querySelector(`[name="${CSS.escape(p.name)}"]`);
                if (el) params[p.name] = el.value;
            }
            return params;
        }

        function draw() {
            if (!last) return;
            results.innerHTML = last.error ? renderError(last.meta, last.error)
                : renderResult(last.meta, last.data, last.params, view);
        }

        async function run() {
            const meta = queries[select.value];
            const params = currentParams(meta);
            const u = new URL(window.location.href);
            u.search = "";
            u.searchParams.set("q", meta.id);
            for (const [k, v] of Object.entries(params)) u.searchParams.set(k, v);
            history.replaceState(null, "", u);
            runBtn.disabled = true;
            runBtn.classList.add("loading");
            try {
                last = { meta, params, data: await recommend(meta.id, params) };
            } catch (e) {
                last = { meta, params, error: e.message };
            } finally {
                runBtn.disabled = false;
                runBtn.classList.remove("loading");
            }
            draw();
        }

        const initial = {};
        url.searchParams.forEach((v, k) => { if (k !== "q" && k !== "run") initial[k] = v; });
        buildForm(queries[select.value], initial);

        select.addEventListener("change", () => {
            buildForm(queries[select.value], {});
            results.innerHTML = "";
            last = null;
        });
        document.getElementById("rec-form").addEventListener("submit", (e) => { e.preventDefault(); run(); });
        document.querySelectorAll(".view-toggle [data-view]").forEach((b) => {
            b.addEventListener("click", () => {
                view = b.dataset.view;
                document.querySelectorAll(".view-toggle [data-view]").forEach((x) => x.classList.toggle("active", x === b));
                draw();
            });
        });
        if (url.searchParams.get("run") === "1") run();
    }

    // ------------------------------------------------------------ каталог
    function initCatalogPage() {
        const tabs = document.querySelectorAll(".tabs [data-tab]");
        function show(key) {
            tabs.forEach((t) => t.classList.toggle("active", t.dataset.tab === key));
            document.querySelectorAll(".tab-pane").forEach((p) => p.classList.toggle("active", p.dataset.pane === key));
        }
        tabs.forEach((t) => t.addEventListener("click", (e) => {
            e.preventDefault();
            show(t.dataset.tab);
            const u = new URL(window.location.href);
            u.searchParams.set("tab", t.dataset.tab);
            u.hash = "";
            history.replaceState(null, "", u);
        }));
        if (location.hash) {
            const target = document.getElementById(decodeURIComponent(location.hash.slice(1)));
            if (target) {
                const pane = target.closest(".tab-pane");
                if (pane) show(pane.dataset.pane);
                target.classList.add("highlight");
                target.scrollIntoView({ block: "center" });
            }
        }
    }

    window.Rehab = { initPatientPage, initRecommendPage, initCatalogPage, humanize, formatValue };
})();
