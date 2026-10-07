import time

from . import files, hosting, local, snapshot, update
from .assigns import KINDS, SUBMISSION, Registry
from .config import Course, StudyError, soft
from .fmt import failures, md_table, moment, plain, short_name, weekday
from .moodle import PENDING, comment_rows, submission_state
from .snapshot import load_state, save_state

USEFUL = {"contentfiles", "introfiles", "configuration", "contents", "files"}
FILES = {"contentfiles", "files", "contents"}
AUTO_EVENTS = {"assign_due_soon", "assign_due_digest", "assign_notification", "newlogin"}
DAY = 86400
URGENT = 2 * DAY
HOT = 7 * DAY
MONTH = 30 * DAY


def pending(a):
    return a["submission"] in PENDING or a["submission"] in (None, "offline")


def news(course, m, section, what, files_=(), links=()):
    return {"course": course, "section": section, "item": m["name"],
            "modname": m.get("modname", ""), "files": list(files_), "links": list(links),
            "what": what}


def by_due(items):
    return sorted(items, key=lambda x: (x["due"]["ts"], x["course"].get("code") or "",
                                        x["short"]))


def in_window(ts, now, horizon):
    return now <= ts <= horizon


def live_ids(items, now, horizon):
    return [i for i, a in items.items() if a["due"]
            and (in_window(a["due"]["ts"], now, horizon)
                 or a["due"]["ts"] < now <= a["due"]["ts"] + MONTH)]


def changes(items, known, since, now):
    new, moved = [], []
    for i, a in items.items():
        prev, due = known.get(i), a["due"]["ts"] if a["due"] else 0
        if since and prev is None and not a["retake"]:
            new.append(i)
        elif prev is not None and due and prev != due:
            moved.append({**a, "was": moment(prev, now)})
    return new, moved


def with_submission(item, s, fb, now, cm=None):
    due = item["due"]
    if s["due"] and s["due"] != (due or {}).get("ts"):
        due = moment(s["due"], now)
    return {**item, "submission": s["status"], "grade": s["grade"], "feedback": s["feedback"],
            "graded": s["graded"], "closed": s["closed"], "canedit": s["canedit"],
            "locked": s["locked"], "opens": moment(s["opens"], now) if s["opens"] else None,
            "due": due,
            "feedback_new": bool(s["feedback"]) and fb is not None
            and fb.get(str(item["assign_id"])) != s["feedback"],
            "comments": [{**c, "time": moment(c["time"], now)} for c in s.get("comments", [])],
            "comments_new": [{**c, "time": moment(c["time"], now)} for c in s.get("comments", [])
                             if cm is not None and not c["own"]
                             and c["id"] not in (cm.get(str(item["assign_id"])) or [])]}


def with_statuses(items, statuses, fb, now, cm=None):
    return {i: with_submission(a, statuses[a["assign_id"]], fb, now, cm)
            if statuses.get(a["assign_id"]) else a for i, a in items.items()}


def originals(retakes, items):
    labs = {(a["course"]["id"], a["lab"]): a for a in items.values() if a["lab"]}
    return {r["cmid"]: labs.get((r["course"]["id"], r["retake"])) for r in retakes}


def retake_info(retakes, items):
    return {cmid: {"retake_of": orig["assign_id"] if orig else None,
                   "needed": orig is None or (orig["submission"] != "submitted"
                                              and not orig["graded"]
                                              and (not orig["due"] or orig["due"]["overdue"]
                                                   or orig["closed"]))}
            for cmid, orig in originals(retakes, items).items()}


def merged(a, *extras):
    for extra in extras:
        a = {**a, **extra.get(a["cmid"], {})}
    return a


def deadline_sections(soon, overdue):
    deadlines = [a for a in soon if a.get("needed", True)]
    late = [a for a in overdue if a.get("needed", True)]
    live = by_due(soon + overdue)
    return {
        "deadlines": deadlines,
        "overdue": [a for a in late if pending(a)],
        "submitted": [a for a in late if not pending(a)],
        "not_started": [a for a in late + deadlines
                        if a["source"] == "assign_api" and a["submission"] in PENDING
                        and not a["closed"]],
        "feedback": [a for a in live if a.get("feedback_new")],
        "comments": [a for a in live if a.get("comments_new")],
        "retakes": [{"assign_id": a.get("assign_id"), "cmid": a["cmid"], "short": a["short"],
                     "course": a["course"], "due": a["due"], "retake_of": a["retake_of"],
                     "needed": a["needed"]} for a in live if a.get("retake")],
    }


def quiz_item(q, tries, course, now):
    states = [t.get("state") for t in tries or []]
    return {"kind": "quiz", "source": "quiz", "quiz_id": q["id"], "course": course,
            "name": q["name"], "short": short_name(q["name"]),
            "due": moment(q["timeclose"], now),
            "submission": "submitted" if "finished" in states else None,
            "opens": moment(q["timeopen"], now) if (q.get("timeopen") or 0) > now else None,
            "open_attempt": any(st in ("inprogress", "overdue") for st in states),
            "attempts_used": None if tries is None else len(tries),
            "attempts_max": q.get("attempts") or None,
            "timelimit_min": (q.get("timelimit") or 0) // 60 or None}


def flagged_rows(course, changed, modules):
    rows = {}
    for u in changed:
        kinds = {x["name"] for x in u["updates"]} & USEFUL
        if kinds:
            m, section = modules.get(u["id"], ({"name": f"(модуль {u['id']})"}, ""))
            rows[u["id"]] = news(course, m, section,
                                 "новые файлы" if kinds & FILES else "изменены настройки")
    return rows


def content_rows(course, modules, since, known):
    rows = {}
    for mid, (m, section) in modules.items():
        fresh = [c for c in m.get("contents") or [] if files.fresh(m, c, since, known)]
        new_files = [files.label(c) for c in fresh if files.is_file(c) and c.get("filesize")]
        links = [c["fileurl"] for c in fresh if files.is_link(c)]
        if new_files or links:
            rows[mid] = news(course, m, section, "новые файлы" if new_files else "новая ссылка",
                             new_files, links)
    return rows


def update_rows(course, changed, modules, since, known):
    flagged = flagged_rows(course, changed, modules)
    fresh = content_rows(course, modules, since, known)
    both = {mid: {**flagged.get(mid, r), "files": r["files"], "links": r["links"]}
            for mid, r in fresh.items()}
    return list({**flagged, **both}.values())


def fresh_discussions(discussions, known, since):
    return [d for d in discussions
            if (d["id"] not in known if known is not None
                else (d.get("timemodified") or d.get("created") or 0) > since)]


def course_grades(course, report, known):
    before = (known or {}).get(str(course["id"]), {})
    out = []
    for t in report:
        got = [i for i in t.get("gradeitems", [])
               if i.get("graderaw") is not None and i.get("itemtype") != "course"]
        if not got:
            continue
        total = next((i for i in t.get("gradeitems", []) if i.get("itemtype") == "course"), None)
        raw = total.get("graderaw") if total else None
        tot = ({"raw": raw, "max": total["grademax"], "computed": False} if raw is not None else
               {"raw": sum(i["graderaw"] for i in got),
                "max": (total or {}).get("grademax") or sum(i["grademax"] for i in got),
                "computed": True})
        items = [{"name": i["itemname"], "short": short_name(i["itemname"], tail=False),
                  "raw": i["graderaw"], "max": i["grademax"],
                  "new": known is not None and before.get(i["itemname"]) != i["graderaw"]}
                 for i in got]
        out.append({"course": course, "items": items, "total": tot})
    return out


def outside_courses(events, tracked, ignore, now, horizon):
    groups = {}
    for e in events:
        c = e.get("course") or {}
        if (c.get("id") and c["id"] not in tracked and c["id"] not in ignore
                and in_window(e.get("timesort", 0), now, horizon)):
            groups.setdefault((c["id"], c.get("fullname") or c.get("shortname")), []).append(e)
    return [{"course": {"id": cid, "title": name}, "count": len(evs),
             "nearest": {"name": (min(evs, key=lambda x: x["timesort"])["name"] or "")[:60],
                         "at": moment(min(e["timesort"] for e in evs), now)}}
            for (cid, name), evs in groups.items()]


class Collector:

    def __init__(self, cfg, moodle, days, state, errors=()):
        self.moodle = moodle
        self.now = int(time.time())
        self.days = days
        self.horizon = self.now + days * DAY
        self.state = state
        self.since = state.get("last_run")
        self.errors = list(errors)
        self.courses = {c.id: c for c in cfg.track(moodle.courses())}
        self.reg = Registry(moodle, soft=self.soft, contents=self.contents)
        self.ignore = cfg.ignore()
        self._contents = {}

    def soft(self, where):
        return soft(self.errors, where)

    def course(self, cid):
        c = self.courses.get(cid)
        return c.as_dict() if c else {"id": cid, "code": None, "title": ""}

    def contents(self, cid):
        if cid not in self._contents:
            self._contents[cid] = None
            with self.soft(f"состав курса {cid}"):
                self._contents[cid] = self.moodle.contents(cid)
        return self._contents[cid] or []

    def fetch_statuses(self, items, raw, got):
        out = dict(got)
        for a in items:
            aid = a["assign_id"]
            if aid in out:
                continue
            out[aid] = None
            with self.soft(f"статус задания {aid}"):
                out[aid] = submission_state(raw[aid], self.moodle.submission_status(aid),
                                            self.now)
            out[aid] = out[aid] and {**out[aid], "comments": self.comments(a, out[aid])}
        return out

    def comments(self, a, s):
        if not s["submission_id"]:
            return []
        with self.soft(f"комментарии к ответу {a['assign_id']}"):
            return comment_rows(self.moodle.comments(a["cmid"], s["submission_id"]),
                                self.moodle.me()["userid"])
        return []

    def activity_items(self, seen):
        others = set(KINDS) - {"assign"}
        out = []
        for course in self.courses.values():
            works = [w for w in self.reg.works(course) if w.cmid not in seen]
            works += self.reg.modules(course, others)
            out += [w.item(self.now) for w in works
                    if w.due and in_window(w.due, self.now, self.horizon)]
        return out

    def fetch_choices(self, items):
        picks = [a for a in items if a.get("modname") == "choice"]
        by_cmid, out = {}, {}
        if not picks:
            return out
        with self.soft("темы докладов"):
            by_cmid = {c["coursemodule"]: c["id"]
                       for c in self.moodle.choices({a["course"]["id"] for a in picks})}
        for a in picks:
            cid = by_cmid.get(a["cmid"])
            if not cid:
                continue
            with self.soft(f"варианты выбора {cid}"):
                opts = self.moodle.choice_options(cid)
                mine = [o["text"] for o in opts if o.get("checked")]
                out[a["cmid"]] = {
                    "choice": {"chosen": mine[0] if mine else None,
                               "options": sum(1 for o in opts if not o.get("disabled"))},
                    "submission": "submitted" if mine else "new"}
        return out

    def quizzes(self):
        out = []
        with self.soft("тесты"):
            for q in self.moodle.quizzes(list(self.courses)):
                close = q.get("timeclose") or 0
                if not close or not self.now <= close <= self.now + MONTH:
                    continue
                tries = None
                with self.soft(f"попытки теста {q['id']}"):
                    tries = self.moodle.quiz_attempts(q["id"])
                out.append(quiz_item(q, tries, self.course(q["course"]), self.now))
        return by_due(out)

    def updates(self):
        out = []
        if not self.since:
            return out
        for cid in self.courses:
            changed = []
            with self.soft(f"обновления курса {cid}"):
                changed = [u for u in self.moodle.updates_since(cid, self.since)
                           if u.get("updates")]
            modules = {m["id"]: (m, sec["name"]) for sec in self.contents(cid)
                       for m in sec.get("modules", [])}
            known = (self.state.get("files") or {}).get(str(cid))
            out += update_rows(self.course(cid), changed, modules, self.since,
                               set(known) if known is not None else None)
        return out

    def announcements(self):
        out, seen = [], {}
        if not self.since:
            return out, seen
        forums = []
        with self.soft("форумы"):
            forums = [f for f in self.moodle.forums(list(self.courses)) if f.get("type") == "news"]
        for f in forums:
            cid = f.get("course")
            if cid not in self.courses:
                continue
            with self.soft(f"объявления курса {cid}"):
                known = (self.state.get("announcements") or {}).get(str(cid))
                seen.setdefault(cid, [])
                found = self.moodle.discussions(f["id"])
                seen[cid] += [d["id"] for d in found]
                for d in fresh_discussions(found, known, self.since):
                    ts = d.get("timemodified") or d.get("created") or 0
                    out.append({"id": d["id"], "course": self.course(cid),
                                "at": moment(ts, self.now),
                                "subject": plain(d.get("subject") or d.get("name"), 120),
                                "author": d.get("userfullname") or "",
                                "text": plain(d.get("message"), 200)})
        return sorted(out, key=lambda a: -a["at"]["ts"]), seen

    def notifications(self):
        out = []
        with self.soft("уведомления"):
            for m in self.moodle.notifications(limit=20):
                if m["timecreated"] > (self.since or 0) and m.get("eventtype") not in AUTO_EVENTS:
                    out.append({"id": m["id"], "at": moment(m["timecreated"], self.now),
                                "subject": plain(m.get("subject"), 120)})
        return sorted(out, key=lambda n: -n["at"]["ts"])

    def grades(self):
        out = []
        for cid in self.courses:
            with self.soft(f"оценки, курс {cid}"):
                try:
                    report = self.moodle.grades(cid)
                except StudyError as e:
                    if e.code == "nopermissiontoviewgrades":
                        continue
                    raise
                out += course_grades(self.course(cid), report, self.state.get("grades"))
        return out

    def outside(self):
        events = []
        with self.soft("календарь"):
            events = self.moodle.calendar(self.now - 7 * DAY, self.now + 120 * DAY)
        return outside_courses(events, self.courses, self.ignore, self.now, self.horizon)

    def run(self):
        return self.gather()[0]

    def gather(self):
        now, fb = self.now, self.state.get("feedback")
        cm = self.state.get("comments")
        works = [w for c in self.courses.values() for w in self.reg.works(c, contents=False)]
        raw = {w.assign_id: w.raw for w in works}
        base = {str(w.assign_id): w.item(now) for w in works}
        new_ids, moved = changes(base, self.state.get("assignments", {}), self.since, now)

        live = by_due([base[i] for i in live_ids(base, now, self.horizon)])
        retakes = [a for a in live if a["retake"]]
        st = self.fetch_statuses([a for a in live if not a["retake"]], raw, {})
        items = with_statuses(base, st, fb, now, cm)
        st = self.fetch_statuses([o for o in originals(retakes, items).values() if o], raw, st)
        items = with_statuses(base, st, fb, now, cm)
        info = retake_info(retakes, items)
        st = self.fetch_statuses([a for a in retakes if info[a["cmid"]]["needed"]], raw, st)
        items = with_statuses(base, st, fb, now, cm)
        ids = [str(a["assign_id"]) for a in live]
        soon_ids = [i for i in ids if in_window(items[i]["due"]["ts"], now, self.horizon)]
        late_ids = [i for i in ids if items[i]["due"]["ts"] < now]

        extras = self.activity_items({a["cmid"] for a in base.values()})
        later = [a for a in extras if a["source"] == "course_contents" and a["retake"]]
        st = self.fetch_statuses([o for o in originals(later, items).values() if o], raw, st)
        items = with_statuses(base, st, fb, now, cm)
        info = {**info, **retake_info(later, items)}
        picks = self.fetch_choices(extras)

        soon = by_due([merged(items[i], info) for i in soon_ids]
                      + [merged(a, info, picks) for a in extras])
        overdue = by_due([merged(items[i], info) for i in late_ids])
        quizzes = self.quizzes()
        announcements, seen = self.announcements()
        updates = self.updates()
        notifications = self.notifications()
        grades = self.grades()
        outside = self.outside()
        known = self.state.get("courses")
        data = {
            "schema": 1, "now": moment(now, now), "days": self.days,
            "first_run": not self.since,
            "since": moment(self.since, now) if self.since else None,
            "courses": [c.as_dict() for c in self.courses.values()],
            "new_courses": [c.as_dict() for c in self.courses.values()
                            if known is not None and str(c.id) not in known],
            **deadline_sections(soon, overdue),
            "quizzes": quizzes, "announcements": announcements, "updates": updates,
            "new_assignments": [items[i] for i in new_ids], "moved": moved,
            "notifications": notifications, "grades": grades, "outside": outside,
            "errors": list(self.errors),
        }
        snap = snapshot.build(
            now, self.state, {str(c.id): c.title for c in self.courses.values()},
            {i: raw[a["assign_id"]].get("duedate") or 0 for i, a in base.items()},
            {str(g["course"]["id"]): {i["name"]: i["raw"] for i in g["items"]} for g in grades},
            {str(cid): files.keys(c) for cid, c in self._contents.items() if c is not None},
            seen,
            {str(a["assign_id"]): a["feedback"] for a in items.values() if a.get("feedback")},
            {str(a["assign_id"]): [c["id"] for c in a["comments"]] for a in items.values()
             if a.get("comments")})
        return data, snap


def collect(cfg, moodle, days=None, save=True, since=None):
    errors = []
    data, snap = Collector(cfg, moodle, days or cfg.days(),
                           load_state(cfg, since, errors), errors).gather()
    if save:
        save_state(cfg, snap)
    return data


def attempts(q):
    used = "?" if q["attempts_used"] is None else q["attempts_used"]
    return f"{used} из {q['attempts_max'] or '∞'}"


def status_of(a):
    pick = a.get("choice")
    if pick:
        return ("выбрана: " + pick["chosen"] if pick["chosen"]
                else f"не выбрана, {pick['options']} вариантов")
    if a["submission"] is None:
        return KINDS.get(a.get("modname"), "?") if a["kind"] == "activity" else "?"
    if a.get("opens") and a["submission"] in PENDING:
        return "откроется " + a["opens"]["text"]
    if a.get("closed"):
        return "заблокировано" if a.get("locked") else "приём закрыт"
    if a["submission"] == "reopened" and a.get("feedback"):
        return "на доработку: " + plain(a["feedback"], 60)
    return SUBMISSION.get(a["submission"], a["submission"])


def label(a):
    return a["course"]["code"] or a["course"]["title"]


def bold(cells):
    return [f"**{c}**" if c not in ("", "—") else c for c in cells]


def when(m):
    return m["text"] if m else "—"


def repo_trouble(c):
    repo = c["repo"]
    if not repo:
        return None
    bad = []
    if repo["dirty"]:
        bad.append(f"незакоммичено {len(repo['dirty'])}")
    for u in c["unreleased_tags"]:
        bad.append(f"нет релиза на {u['hosting']} ({', '.join(u['tags'])})")
    for name, r in c["releases"].items():
        latest = r.get("latest")
        if latest and not latest.get("assets"):
            bad.append(f"релиз {latest['tag']} на {name} без файлов")
    return f"{c['code']}: {', '.join(bad)}" if bad else None


def news_rows(t):
    rows = []
    for u in t.get("updates", []):
        if u.get("pulled"):
            files_ = ", ".join(u["pulled"])
        elif not u["files"]:
            files_ = ""
        elif u["course"]["code"]:
            files_ = ", ".join(u["files"]) + " — не скачаны"
        else:
            files_ = ", ".join(u["files"]) + " — у курса нет папки (CODE в config.env)"
        parts = [files_] if files_ else []
        parts += ["ссылка → " + url for url in u.get("links", [])]
        rows.append([label(u), u["section"] or "—", f"{u['item']}: {u['what']}",
                     "; ".join(parts) or "—"])
    for a in t.get("new_assignments", []):
        rows.append([label(a), "—", f"новое задание: {a['short']}, до {when(a['due'])}", "—"])
    for a in t.get("moved", []):
        rows.append([label(a), "—", (f"срок сдвинут: {a['short']}, было {when(a['was'])} "
                                     f"→ стало {when(a['due'])}"), "—"])
    return rows


def deadline_rows(t):
    rows = [bold([a["due"]["text"], "просрочено", a["short"], label(a), status_of(a)])
            for a in t.get("overdue", [])]
    for a in t.get("deadlines", []):
        if a["submission"] == "submitted":
            continue
        cells = [a["due"]["text"], a["due"]["left"], a["short"], label(a), status_of(a)]
        rows.append(bold(cells) if a["due"]["left_sec"] < URGENT else cells)
    return rows


def announcement(a):
    return f"**{a['subject']}** · {a['author']}: {a['text']}"


def grade_rows(t):
    rows = []
    for g in t.get("grades", []):
        fresh = [f"{i['short']} {i['raw']:.2f}/{i['max']:g}" for i in g["items"] if i["new"]]
        rows.append([label(g), f"{g['total']['raw']:.2f} / {g['total']['max']:g}",
                     " · ".join(fresh) or "—"])
    return rows


def quiz_rows(t):
    rows = []
    for q in t.get("quizzes", []):
        if q["submission"] == "submitted":
            continue
        tries = ((f"откроется {q['opens']['text']}; " if q.get("opens") else "")
                 + ("начат, не отправлен; " if q["open_attempt"] else "") + attempts(q))
        cells = [q["due"]["text"], q["due"]["left"], q["short"], label(q), tries,
                 f"{q['timelimit_min']} мин" if q["timelimit_min"] else "—"]
        rows.append(bold(cells) if q["due"]["left_sec"] < URGENT or q["open_attempt"] else cells)
    return rows


def hot_line(a):
    code = a["course"]["code"]
    left = "просрочено" if a["due"]["overdue"] else a["due"]["left"]
    return (f"- **{a['short']}** · {label(a)} · до {a['due']['text']} · {left} · "
            f"методички: {code + '/stash/' if code else 'каталога курса нет'}")


def outside_rows(t):
    return [[o["nearest"]["at"]["text"], o["nearest"]["name"],
             f"{o['course']['title']} (id {o['course']['id']}, ещё {o['count']})"]
            for o in t.get("outside", [])]


def render(d):
    t = d.get("tuis") or {}
    now = d["now"]["ts"]
    out = [f"# Учёба · {weekday(now)} {d['now']['text']}"]
    if t.get("first_run"):
        out.append("\nПервый запуск: обновления в курсах начнут отслеживаться со следующего раза. "
                   "Материалы курсов пока не скачаны: `study files --pull` — "
                   "в пустую stash/ забирает всё.")
    for c in t.get("new_courses", []):
        out.append(f"\nНовый курс в ТУИС: {c['title']} (id {c['id']}) — "
                   + (f"папка {c['code']}." if c["code"] else
                      f"строка `CODE {c['id']} <папка>` или `COURSE_IGNORE` в config.env."))

    news = news_rows(t)
    rows = deadline_rows(t)
    if rows:
        out += ["\n## Сроки\n",
                md_table(rows, ["Когда", "Осталось", "Работа", "Курс", "Состояние"])]
    elif d.get("tuis") is None:
        out.append("\nТУИС не опрашивался (`--local`): только состояние репозиториев.")
    else:
        tail = "" if news or t.get("first_run") or t.get("new_courses") else " Обновлений нет."
        out.append(f"\nСроков в ближайшие {d['days']} дн нет.{tail}")

    trouble = [s for s in map(repo_trouble, d["courses"]) if s]
    if trouble:
        out.append("\n" + "; ".join(trouble) + ".")

    named = {c["id"] for c in t.get("new_courses", [])}
    unset = [c for c in t.get("courses", []) if not c["code"] and c["id"] not in named]
    if unset:
        out.append("\nБез папки (файлы не скачиваются): "
                   + ", ".join(f"{c['title']} (id {c['id']})" for c in unset)
                   + " — строка `CODE <id> <папка>` или `COURSE_IGNORE` в config.env.")

    sections = [
        ("Тесты", quiz_rows(t), ["Когда", "Осталось", "Тест", "Курс", "Попытки", "Время"]),
        ("Баллы", grade_rows(t), ["Курс", "Итого", "Новое"]),
        ("Отзывы", [[label(a), a["short"], a["feedback"]] for a in t.get("feedback", [])],
         ["Курс", "Работа", "Отзыв преподавателя"]),
        ("Комментарии к ответам",
         [[label(a), a["short"], c["author"], c["text"]] for a in t.get("comments", [])
          for c in a["comments_new"]], ["Курс", "Работа", "Автор", "Комментарий"]),
        ("Уведомления", [[n["at"]["text"], n["subject"]] for n in t.get("notifications", [])],
         ["Когда", "Тема"]),
        ("Объявления", [[a["at"]["text"], label(a), announcement(a)]
                        for a in t.get("announcements", [])], ["Когда", "Курс", "Тема"]),
        ("Новое в курсах", news, ["Курс", "Раздел", "Что", "Файлы"]),
        ("Сроки в скрытых курсах", outside_rows(t), ["Когда", "Работа", "Курс"]),
    ]
    for title, rows, headers in sections:
        if rows:
            out += [f"\n## {title}\n", md_table(rows, headers)]
    hot = [a for a in t.get("not_started", []) if a["due"]["left_sec"] < HOT]
    if hot:
        out += ["\n## Горит\n"] + [hot_line(a) for a in hot]
    if d.get("errors"):
        out.append("\n" + failures(d["errors"]) + ".")
    hints = update.note(d.get("update"))
    if hints:
        out.append("\n" + "\n".join(hints))
    return "\n".join(out)


def render_digest(d):
    return render({"now": d["now"], "days": d["days"], "tuis": d, "courses": [],
                   "errors": d["errors"]})



def pull_updates(cfg, moodle, tuis, errors):
    pulled = {}
    for c in tuis["courses"]:
        todo = [u for u in tuis["updates"] if u["files"] and u["course"]["id"] == c["id"]]
        if not todo or not c["code"]:
            continue
        wanted = {n for u in todo for n in u["files"]}
        with soft(errors, f"файлы, курс {c['code']}"):
            d = files.listing(cfg, moodle, Course(c["id"], c["code"], c["title"]),
                              everything=True)
            d["files"] = [f for f in d["files"] if f["name"] in wanted]
            got = files.pull(moodle, d)
            names = [g["name"] for g in got["pulled"]]
            pulled[c["id"]] = names
            errors.extend(got["errors"])
    return {**tuis, "updates": [
        {**u, "pulled": [n for n in u["files"] if n in pulled[u["course"]["id"]]]}
        if u["files"] and u["course"]["id"] in pulled else u for u in tuis["updates"]]}


def host_state(cfg, repo, cls, tags, course, errors):
    slug = local.repo_from_remote(repo, cls.remote, cls.host)
    release, missing = {"ok": False, "latest": None}, []
    with soft(errors, f"{cls.source}, курс {course.code}"):
        rels = cls(cfg, path=repo).releases()
        names = [r["tag"] for r in rels]
        release = {"ok": True, "latest": rels[0] if rels else None, "tags": names}
        missing = [t for t in tags if t not in names]
    return slug or None, release, missing


def lab_state(lab, found):
    return {**lab,
            "tuis": ({"assign_id": found["assign_id"], "name": found["name"],
                      "due": found["due"], "submission": found["submission"],
                      "matched_by": "number"} if found else None),
            "ready": {"report": lab["report"]["built"],
                      "presentation": lab["presentation"]["built"],
                      "videos": lab["videos"]["filled"] == lab["videos"]["total"],
                      "submitted": bool(found and found["submission"] == "submitted")}}


def course_state(cfg, course, by_lab, errors):
    flow = local.flow_of(cfg, course.code)
    head = {**course.as_dict(), "dir": str(course.dir), "flow": flow}
    repo = local.course_repo(course.code) if flow == "release" else None
    if not repo:
        return {**head, "repo": None, "releases": {}, "unreleased_tags": [], "labs": []}
    info = local.repo_state(repo)
    hosts = {cls.source: host_state(cfg, repo, cls, info["tags"], course, errors)
             for cls in hosting.HOSTS.values()}
    return {**head, "repo": {**info, "remotes": {s: h[0] for s, h in hosts.items()}},
            "releases": {s: h[1] for s, h in hosts.items()},
            "unreleased_tags": [{"hosting": s, "tags": h[2]} for s, h in hosts.items() if h[2]],
            "labs": [lab_state(lab, by_lab.get((course.code, lab["num"])))
                     for lab in local.labs(repo, course.code)]}


def state(cfg, moodle, days=None, with_tuis=True, save=True, pull=False, since=None):
    errors = []
    tuis = None
    if with_tuis:
        tuis = collect(cfg, moodle, days=days, save=save, since=since)
        if pull:
            tuis = pull_updates(cfg, moodle, tuis, errors)

    t = tuis or {}
    by_lab = {(a["course"]["code"], a["lab"]): a
              for a in t.get("deadlines", []) + t.get("overdue", []) + t.get("submitted", [])
              if a.get("lab") and a["course"].get("code")}
    titles = {c["id"]: c["title"] for c in t.get("courses", [])}
    courses = [course_state(cfg, Course(cid, code, titles.get(cid, "")), by_lab, errors)
               for cid, code in cfg.codes().items()]

    upd = None
    with soft(errors, "обновление study"):
        upd = update.check()

    return {"schema": 1, "now": moment(int(time.time())), "days": days or cfg.days(),
            "tuis": tuis, "courses": courses, "update": upd,
            "errors": errors + t.get("errors", [])}
