<div align="center">

# OPEN CLI AGENT

### وكيلك الذكي المحلي للطرفية.<br/>خاص. معزول. يستأذنك قبل أن يتصرف.

<br/>

[English](README.md) · **العربية**

<br/>

![Status](https://img.shields.io/badge/STATUS-WORK%20IN%20PROGRESS-orange?style=for-the-badge)
![Python](https://img.shields.io/badge/PYTHON-3.14-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Ollama](https://img.shields.io/badge/RUNS%20ON-OLLAMA-black?style=for-the-badge)
![Sandbox](https://img.shields.io/badge/SANDBOX-BUBBLEWRAP-green?style=for-the-badge)

<br/>

[المعاينة](#-المعاينة) · [المميزات](#-المميزات) · [البدء السريع](#-البدء-السريع) · [الاستخدام](#-الاستخدام) · [الأمان](#-نموذج-الأمان) · [البنية](#-البنية) · [خارطة الطريق](#-خارطة-الطريق)

</div>

<br/>

<div dir="rtl">

> [!WARNING]
> **قيد التطوير.** المشروع نشط وليس إصداراً رسمياً بعد. توقّع بعض الخشونة، وقد تتغير الأوامر والسلوك.

</div>

<br/>

<div align="center">
  <img src="docs/assets/ai_agent_github.png" width="100%" alt="نظرة عامة على OPEN CLI AGENT" />
</div>

---

<div dir="rtl">

## ✦ المعاينة

</div>

<div align="center">
  <img src="docs/assets/preview.gif" width="100%" alt="عرض OPEN CLI AGENT" />
</div>

---

<div dir="rtl">

## ✦ لماذا

أغلب وكلاء البرمجة تعمل في السحابة وتنفّذ أوامر على جهازك برقابة قليلة. **OPEN CLI AGENT** يعكس ذلك:

- **محلي 100%.** النماذج تعمل عبر [Ollama](https://ollama.com). بدون مفاتيح API، وبياناتك لا تغادر جهازك.
- **آمن بالتصميم.** كل أمر يمر على طبقة صلاحيات ويعمل داخل صندوق معزول.
- **مناسب لأي جهاز.** اختر مستوى النموذج الذي يناسب جهازك.
- **السرعة أولاً.** تسخين مسبق للنموذج وطلبات قابلة للإلغاء تبقيه سريع الاستجابة.

---

## ✦ المميزات

| | |
|---|---|
| 🖥️ **واجهة TUI كاملة** | واجهة هادئة أحادية اللون، كتل للأدوات، شريط استهلاك السياق، و`Esc` للإيقاف |
| 🔐 **طبقة الصلاحيات** | الأوامر الآمنة تعمل، الخطرة تُحظر، والباقي يطلب موافقتك |
| 📦 **صندوق معزول** | bubblewrap: الشبكة مغلقة، المجلد الشخصي مخفي، و`.git` للقراءة فقط |
| 🧰 **الأدوات** | الطرفية، قراءة وكتابة الملفات (داخل مجلد العمل فقط)، وGit (status/diff/commit) |
| 🧠 **ذاكرة الملاحظات** | ملاحظات لكل مشروع، تُحفظ دائماً بموافقتك الصريحة |
| 💾 **جلسات محفوظة** | استأنف أي جلسة بـ `-c` أو `-s <id>` |
| 🔁 **تسليم ذكي (Handoff)** | عند امتلاء السياق تحصل على ملخص جاهز للنسخ لمتابعة العمل في جلسة جديدة |
| 🌍 **دعم العربية (RTL)** | عرض صحيح من اليمين لليسار، مع الإنجليزية والأرقام المختلطة |
| ⚙️ **ثلاثة مستويات للنماذج** | خفيف ومتوسط وقوي، تختاره حسب جهازك في معالج الإعداد الأول |

<details>
<summary><b>مستويات النماذج</b></summary>

<br/>

| المستوى | النموذج | مناسب لـ |
|---|---|---|
| خفيف | `gemma4:e2b` | الأجهزة ذات الذاكرة القليلة |
| متوسط | `gemma4:e4b` | أغلب اللابتوبات |
| قوي | `gpt-oss:20b` | الأجهزة القوية |

معالج الإعداد الأول يقترح مستوى حسب الذاكرة (RAM). يمكنك تغييره في أي وقت بـ `--setup`.

</details>

---

## ✦ البدء السريع

**المتطلبات:** Python 3، و[Ollama](https://ollama.com)، و[bubblewrap](https://github.com/containers/bubblewrap) (لينكس).

</div>

```bash
# 1. استنساخ المشروع
git clone https://github.com/eh7r/OPEN-CLI-AGENT.git
cd OPEN-CLI-AGENT

# 2. البيئة
python -m venv .venv
source .venv/bin/activate        # fish: source .venv/bin/activate.fish
pip install -r requirements.txt

# 3. تحميل نموذج (اختر مستواك)
ollama pull gemma4:e4b

# 4. التشغيل
python main.py
```

<div dir="rtl">

عند أول تشغيل، يسألك معالج قصير عن مستوى النموذج ولغة العرض.

---

## ✦ الاستخدام

</div>

```bash
python main.py              # الواجهة الكاملة (TUI)
python main.py --plain      # جلسة الطرفية العادية
python main.py -c           # متابعة آخر جلسة
python main.py -s <id>      # متابعة جلسة محددة
python main.py --setup      # إعادة معالج الإعداد
python main.py --notes      # عرض الملاحظات المحفوظة
```

<div dir="rtl">

### أوامر الشرطة المائلة

| الأمر | وظيفته |
|---|---|
| `/help` | عرض الأوامر والاختصارات |
| `/new` | بدء جلسة جديدة |
| `/clear` | مسح الشاشة |
| `/context` | عرض استهلاك السياق |
| `/model` | عرض تفاصيل النموذج |
| `/handoff` | نسخ ملخص المتابعة إلى الحافظة |
| `/exit` | الحفظ والخروج |

اضغط **Esc** لإيقاف مهمة قيد التنفيذ. إذا امتلأ السياق يُنشأ الـ handoff تلقائياً عند 85%.

---

## ✦ نموذج الأمان

الأمان هو جوهر هذا المشروع وليس إضافة.

</div>

```text
Your request → Model → Tool call → Permission layer → Sandbox → Result
                                        │
                                        ├─ blocked   dangerous commands never run
                                        ├─ ask       you approve each risky action
                                        └─ allowed   known-safe commands only
```

<div dir="rtl">

- **نافذة موافقة** لكل كتابة وcommit وأمر غير معروف، تعرض الإجراء بالضبط.
- **أدوات الملفات مقيّدة** بمجلد العمل، والملفات الحساسة (`.env`، المفاتيح) محظورة.
- **صندوق معزول افتراضياً**: بدون شبكة، المجلد الشخصي مخفي، و`/usr` و`.git` للقراءة فقط.
- **الرفض نهائي.** إذا رفضت، لا يحق للوكيل تجربة أداة أخرى للالتفاف عليه.
- **لا إعادة محاولة عمياء** للإجراءات الخطرة، والاستدعاء نفسه يُنفَّذ مرتين كحد أقصى.
- **الملاحظات بيانات غير موثوقة.** تُعرض للنموذج كبيانات وليس كتعليمات.
- **جرى اختبار حقن التعليمات (Prompt Injection)**: التعليمات المخفية داخل الملفات تُرفض.

---

## ✦ البنية

</div>

<div align="center">
  <img src="docs/assets/architecture.jpg" width="100%" alt="بنية النظام" />
</div>

<div dir="rtl">

<details>
<summary><b>هيكل المشروع</b></summary>

</div>

```text
OPEN-CLI-AGENT/
├── main.py              entry point
├── agent/
│   ├── core.py          agent loop
│   ├── model.py         Ollama adapter (streaming, warm-up, cancel)
│   ├── tools.py         tool registry + validation
│   ├── permissions.py   permission layer
│   ├── approval.py      approval flow
│   ├── sandbox.py       bubblewrap sandbox
│   ├── shell.py         command execution
│   ├── file_tools.py    read / write / list
│   ├── git_tools.py     status / diff / commit
│   ├── evaluate.py      observe + retry rules
│   ├── context.py       context trimming
│   ├── memory.py        notes (SQLite)
│   ├── sessions.py      saved sessions
│   ├── journal.py       session journal
│   ├── handoff.py       handoff generation
│   ├── rtl.py           Arabic RTL rendering
│   ├── tui.py           full-screen interface
│   ├── tui_parts.py     widgets and theme
│   ├── events.py        core → UI events
│   ├── cli.py           plain session
│   └── setup.py         first-run wizard
├── tests/               pytest suite
└── docs/                guides and assets
```

<div dir="rtl">

</details>

---

## ✦ الإعدادات

تُحفظ في `~/.config/ai-agent/config.json`. ومتغيرات البيئة لها الأولوية عليها.

| المتغير | تأثيره |
|---|---|
| `AGENT_SANDBOX=off` | تعطيل الصندوق المعزول (مع تحذير) |
| `AGENT_SANDBOX_NET=1` | السماح بالشبكة داخل الصندوق |
| `AGENT_THINK=1` | تفعيل "تفكير" النموذج (أبطأ) |
| `AGENT_RTL=on\|off` | فرض معالجة RTL للعربية |
| `AGENT_RTL_MODE=words\|bidi` | اختيار استراتيجية RTL |
| `AGENT_TRACE=1` | تسجيل أزمنة الطلبات في `/tmp/agent-trace.log` |

الجلسات تُحفظ في `~/.local/share/ai-agent/sessions/`.

---

## ✦ التطوير

</div>

```bash
pip install -r requirements-dev.txt
pytest -q
```

<div dir="rtl">

---

## ✦ خارطة الطريق

- [x] نواة الوكيل، سجل الأدوات، طبقة الصلاحيات
- [x] أدوات حقيقية للطرفية والملفات وGit
- [x] صندوق bubblewrap المعزول
- [x] ذاكرة الملاحظات وإدارة السياق
- [x] معالج الإعداد الأول والردود المتدفقة
- [x] واجهة TUI كاملة مع نافذة الموافقة
- [x] عرض العربية من اليمين لليسار
- [x] الجلسات المحفوظة والـ handoff
- [ ] أوامر `/sessions` و`/notes` و`/memory` و`/setup`
- [ ] التغليف (`pipx install`)
- [ ] المهارات (Skills)
- [ ] الموصلات (GitHub، المتصفح)
- [ ] الاختبار على المستويات الثلاثة للنماذج
- [ ] أول إصدار رسمي

---

## ✦ المساهمة

الأفكار وتقارير الأخطاء مرحّب بها. افتح [issue](https://github.com/eh7r/OPEN-CLI-AGENT/issues). ستُفتح طلبات الدمج (Pull Requests) عندما يخرج المشروع من مرحلة التطوير.

---

</div>

<div align="center">

بناء [**Yazeed**](https://github.com/eh7r) · [Yazeed Labs](https://www.youtube.com/@YazeedLabs)

<sub>OPEN CLI AGENT · محلي · خاص · لك</sub>

</div>
