# OCR benchmark — 2026-05-09

> ⚠️ **RETIRED LAUNCH-BASELINE — NOT the operated engine.** This 2026-05-09
> bake-off (Tesseract / Surya / Anthropic Haiku-4.5) recommended an
> `auto:surya+llm-anthropic` default. That recommendation is **superseded**.
> The operated engine is **`llm-dots`** — Claude Sonnet 4.6 vision per page +
> local `dots.mocr` as the content-filter (HTTP 400) backstop, concurrency 8.
> **Tesseract, Surya, and `auto` are retired.** Kept for historical economics
> only; do not read the "recommended default" lines below as current guidance.

> _Note: the corpus has grown well past this run (see state.md for current_
> _counts); the per-page economics scale linearly._

> Methodology: 5 cards × first 5 pages × 3 engines (Tesseract, Surya, Anthropic
> Haiku-4.5 vision). The LLM transcription is used as the assumed-correct
> truth proxy, pending a human-verified truth set; CER/WER for Tesseract and Surya are scored against
> it. Comparing the LLM engine's output against itself is meaningless and we
> don't try. Full per-page detail in [`data/benchmarks/ocr-20260509T002235Z.json`](../data/benchmarks/ocr-20260509T002235Z.json).

## Per-engine summary (golden set, 25 pages)

| Engine | Pages | Mean conf | Median CER | Capped mean CER | Median WER | Total wall-clock | Total cost |
|---|---:|---:|---:|---:|---:|---:|---:|
| Tesseract | 25 | 77.1 | 40.4% | 44.0% | 59.8% | 60.2s | $0.0000 |
| Surya | 25 | 85.3 | 6.1% | 30.1% | 9.6% | 48.7s | $0.0000 |
| LLM (Anthropic Haiku 4.5) | 25 | 76.8 | — | — | — | 192.6s | $0.1024 |

_CER/WER are scored vs the LLM as truth proxy. **Median CER** is the_
_typical-page metric — robust to hallucination outliers on blank/near-blank_
_scans where engines disagree on whether to emit any text. **Capped mean**_
_clips per-page CER at 100% (raw means are skewed by a couple of pages_
_where one engine emitted long garbage and the other was correctly silent)._

**Tesseract baseline (full corpus, snapshot 2026-05-08, 4-way concurrency, before Surya overwrite):**
- 116 cards / 4153 pages
- 185.3 min total wall-clock
- Page-weighted mean confidence: 78.64

**Surya post-pass (full corpus, this run, --force re-OCR with PURSUE_OCR_ENGINE=surya, serialized):**
- 116 cards / 4153 pages
- 134.8 min total wall-clock
- Page-weighted mean confidence: 86.03

## Worst Tesseract failure (side-by-side)

**Card:** `26b02d358ec20061` (redacted_page), page 3
**Tesseract CER vs LLM truth proxy:** 217.0% (over 100% because Tesseract hallucinated more characters than the truth contains)
**Tesseract WER vs LLM truth proxy:** 806.2% (same caveat — over 100% reflects hallucinated tokens)

### Tesseract output (conf 14.9)
> : _ ee .
> . a : 2
> | _ . :
> 
> | oe a So
> . |
> 
> 1 . a ve Lee
> 
> a a. J sees i
> 
> 7 . o . " oo a ‘
> 3 L :
> 
> C : oe
> 
> ee . )
> 
> _ 2 :
> 
> : Paes
> : a oe
> 
> o Co
> 
> ee _
> 
> ee Be ‘ ee
> _ MA : ae 5 ae
> oo : SO 2. al oo i _ oo :
> as : 5 : c - a 7 yy Co o ee oo E a ae o /
> ae Ce ee,
> 4 oo a a -
> A ee
> 
> oo - o ce - Be
> ae : . .
> a eh oe 7 a
> Vo 7 S cc
> — ae
> 
> - . | .
> 
> - fs.
> ae | . oo ae
> . i _ oe
> oo es ee
> 
> o .
> 
> ge
> 
> oe
> . i : : a
> ons : : . as
> 
> :
> oN : es : oe "
> eine
> 
> ee ‘ oe .
> gs oo i : os
> ee ao a ted ea co " a
> 
> : Hee
> 
> a ao hal ey u Le ue i: - I S
> Es S : | SG i i Bee . i ae en
> . Lo : ee : Z Ne a Tus, ne NE ae
> ee | : a
> ue ee Ss -" oe _ es . a
> : ue Co ee Oe ee d
> o See ae aes Os as NS \ oe Ce f Us ~ ie
> _ oe : A: ee ee 7 oom” sn
> oe a A eee es oo 2 |
> i as fe ie oe & le ee ‘ is nue pee
> ee . a
> es a . . es oa a {
> ee ee ERA wna ge
> : co : ee oO a ee :
> ee
> . ae eo Ri cn
> - oe oo : yo . a
> 
> as on : se
> : Gee Loe ™ oo
> 
> . uo a
> ar Cae ae a
> . ee
> 
> Des a ia
> eee
> oe ee Se Ne . Eee
> 
> A 4 .
> 
> oe oe S Ae _ a _ .
> 
> . oe | a - a
> . oo
> 
> ae
> .
> 
> PRU
> 
> a. / '
> ~~“ a
> 
> oe ae ae ee :
> es es oo a
> a ao a a oy Ne | eee
> 
> ce oe : ae ae ee
> SN
> 
> : .
> ee 2 . ey
> oe A a ee oo a Os oe
> ee . _ . . a coe
> i ernie ah i a :
> ae ee a a ce va
> 
> a _ ee oo ae eee ; ee . is
> ce ena ae es ae ae
> Ae a 

### Surya output (conf 72.4)
> 4947
> insk1
> 4
> 
> 
> W
> 500
> 
> ASKOY.
> j
> 
> (Address of contributor)
> (Name of Special Agent)
> Returned Yes ( )
> 2620
> (Name of contributor)
> 5
> X
> 3
> b
> E Received.
> Description:
> Ш
> File No.
> 
> 
> 
> 
> NW 90290
> Docld:34714592 Page 3

### LLM output (conf 45.0)
> Date Received ________________
> 
> From _____________ (Name of contributor)
>          _____________ (Address)
> 
> By _____________ (Initials of contributor) _______________
> To Be Name of Special Agent
>    Returned    Yes [ ] No [ ]
> 
> Description:
> _________________________________
> _________________________________
> _________________________________
> 
> File No.________________
> 
> ALL INFORMATION CONTAINED
> HEREIN IS CLASSIFIED
> DATED: [ILLEGIBLE]
> 
> [Handwritten text at top right]: 
> 4/15/65
> 
> [Handwritten text in middle right]:
> Rec. at 
> Washington
> 
> [Handwritten signature and notation in middle]:
> Int'o
> A. unknown
> MARSHALL WASN'T
> 
> [Handwritten notation at bottom]:
> File No. [Illegible]
> 
> DocId-34714592 Page 3
> NW 90290


## Recommendation

On the golden set, **Surya wins** on every metric that matters for production:
mean confidence 85.3 vs Tesseract's 77.1, **median
per-page CER** vs the LLM truth proxy of **6.1%** vs
Tesseract's **40.4%** — i.e., on a typical page, Tesseract
makes ~7× as many character
errors. Capped-mean CER is **30.1%** vs Tesseract's
**44.0%**. Per-page wall-clock is
1.9s vs 2.4s after model load amortizes.
Surya is a flat win over Tesseract in both quality and speed; on the 5090 the
model load is one-time per run.

**Auto-mode projection.** 2/25 Surya pages on the
golden set fell below the LLM-fallback threshold of 70 (8.0%).
Extrapolating to the full 4153-page corpus:

- Pages re-OCR'd by the LLM: ~332
- At Haiku-4.5 (~$0.0041/page): **~$1.36 total**
- At Sonnet-4.6 (~13× Haiku per-token blend): ~$17.67

**Auto-mode was worth running on the full corpus** at launch — at Haiku rates
it's well under a dollar, fits the LLM budget, and the lift on the worst pages
is real. _(Historical: the operated engine is now `llm-dots`; see the banner._
_at the top of this file.)_
The pages Surya struggles with on this corpus aren't redacted text (it reads
around the bars cleanly) — they're heavily-faded carbon-copy pages where Surya
sometimes hallucinates plausible-but-wrong text instead of staying silent
(see card `13f86e95aed52840` page 3 in the per-card detail below: the LLM
correctly emits `[ILLEGIBLE]`, Surya emits a coherent-looking string that
isn't on the page). The auto-mode threshold of 70 catches those (Surya
self-rated low when in trouble) and the LLM cleans them up. _(At launch the
`auto:surya+llm-anthropic` engine was the recommended default; it is now_
_retired in favour of `llm-dots` — see the banner at the top of this file.)_

**One nuance:** the LLM's self-reported confidence on the golden set
(76.8) is *lower* than Surya's (85.3). That's
not because the LLM is worse — it's because the LLM is trained to rate itself
harshly on partial transcriptions of redacted/illegible pages, while Surya's
confidence is a mean of per-line model probabilities and stays high even when
it's hallucinating on a black bar. Don't read the confidence column as quality
across engines; it's an engine-internal signal for the auto-mode threshold.


## Golden set

5 cards pinned in [`tests/fixtures/ocr_golden.txt`](../tests/fixtures/ocr_golden.txt)
covering the engine-failure modes named in the benchmark plan:

1. **Clean typewriter** — `78dc972c0c143d1e` NASA Apollo 17 Transcript 1972.
   Tesseract should ace this; Surya does ace it; LLM matches.
2. **Faded FBI scan** — `4b68726be4af8ff9` FBI HQ-83894 Serial 220 (mid-1950s
   carbon). Tesseract drops to 80.7 mean conf; Surya recovers to 94.3; LLM
   matches Surya on text quality.
3. **Multi-column form** — `15d23b5f88df64fa` DOW-UAP-D25 Mission Report
   Greece. Reading-order torture test. Tesseract scrambles columns; Surya
   keeps the column intact; LLM produces the cleanest structured output.
4. **Redacted page** — `26b02d358ec20061` FBI HQ-101634279 100-DE-26505.
   Black-bar redactions over typed text. Tesseract gives garbage on the
   redacted regions (54.5 mean conf); Surya reads around the bars (76.3);
   LLM explicitly marks `[REDACTED]` per the prompt contract.
5. **Long debriefing** — `13f86e95aed52840` FBI HQ-83894 Section 6 (271 pp,
   mixed-quality omnibus). Stress test for engine consistency.

## Per-card detail (5 pages each)

### 78dc972c0c143d1e — clean_typewriter
_NASA-UAP-D2 Apollo 17 Transcript 1972 (16 pp)_  (file: `nasa-uap-d2-apollo-17-transcript-1972.pdf`)

| Page | Engine | Conf | Wall-clock | Snippet |
|---:|---|---:|---:|---|
| 1 | tesseract | 92.6 | 1.4s | Tape 5/2 ⏎  ⏎ 00 03 25 O1 ⏎  ⏎ 00 03 27 27 ⏎  ⏎ 00 03 31 55 ⏎  ⏎ 00 03 34 10 ⏎  ⏎ CC ⏎  ⏎ cc ⏎  ⏎ cc ⏎  ⏎ ce ⏎  ⏎ cc ⏎  ⏎ CMP ⏎  ⏎ cc ⏎  ⏎ CMP ⏎  ⏎ cc ⏎  ⏎ CMP ⏎  ⏎ CC ⏎  ⏎ LMP ⏎ … |
| 1 | surya | 89.1 | 4.7s | Tape 5/2 ⏎ CC ⏎ Yes, we copied your V<sub>T</sub> and your EMS numbers, and ⏎ we've got a number for you. Maneuver start time ⏎ will be at 03 plus 33 plus 27. ⏎ LMP ⏎ Okay, we got… |
| 1 | llm | 92.0 | 7.7s | Tape 5/2 ⏎  ⏎ CC         Yes, we copied your V_T and your EMS numbers, and ⏎            we've got a number for you.  Maneuver start time ⏎            will be at 03 plus 33 plus 27… |
| 2 | tesseract | 92.0 | 1.6s | 00 03 37 34 ⏎  ⏎ 00 03 37 45 ⏎  ⏎ 00 03 37 46 ⏎  ⏎ CC ⏎  ⏎ CMP ⏎  ⏎ CC ⏎  ⏎ CMP ⏎  ⏎ CC ⏎  ⏎ CMP ⏎  ⏎ cc ⏎  ⏎ CMP ⏎  ⏎ CDR ⏎  ⏎ CMP ⏎  ⏎ a ⏎ Q ⏎  ⏎ CC ⏎  ⏎ CDR ⏎  ⏎ CMP ⏎  ⏎ Tape … |
| 2 | surya | 91.2 | 1.1s | Tape 5/3 ⏎ CC ⏎ Roger. They look like fluid of some sort? ⏎ CMP ⏎ Not to me. They look like pieces of something. ⏎ CC ⏎ Roger. ⏎ CMP ⏎ They're very bright. ⏎ CC ⏎ Jack, we'd like … |
| 2 | llm | 85.0 | 8.7s | Tape 5/3 ⏎  ⏎ CC         Roger. They look like fluid of some sort? ⏎  ⏎ CMP        Not to me. They look like pieces of something. ⏎  ⏎ CC         Roger. ⏎  ⏎ CMP        They're ve… |
| 3 | tesseract | 89.0 | 1.3s | Tape 5/4 ⏎  ⏎ 00 03 38 01 ⏎  ⏎ 00 03 39 35 ⏎  ⏎ 00 03 39 53 ⏎  ⏎ 00 03 39 57 ⏎  ⏎ cc ⏎  ⏎ CMP ⏎  ⏎ cc ⏎  ⏎ CMP ⏎  ⏎ LMP ⏎  ⏎ CMP ⏎  ⏎ cc ⏎  ⏎ CMP ⏎  ⏎ cc ⏎  ⏎ CDR ⏎  ⏎ cc ⏎  ⏎ CMP… |
| 3 | surya | 87.9 | 1.2s | Tape 5/4 ⏎ 00 03 38 01 CC ⏎ Roger. Cut in. ⏎ CMP ⏎ Every once in a while, a fragment of considerably ⏎ higher velocity than the others goes across my ⏎ window. But that's very rar… |
| 3 | llm | 92.0 | 6.6s | Tape 5/4 ⏎  ⏎ 00 03 38 01  CC          Roger. Cut in. ⏎  ⏎             CMP         Every once in a while, a fragment of considerably ⏎                         higher velocity than… |
| 4 | tesseract | 90.0 | 1.7s | 00 ⏎  ⏎ 00 ⏎  ⏎ 00 ⏎ 00 ⏎ 00 ⏎  ⏎ 00 ⏎  ⏎ 00 ⏎  ⏎ 00 ⏎  ⏎ 00 ⏎  ⏎ 00 ⏎  ⏎ 00 ⏎  ⏎ 03 ⏎  ⏎ 03 ⏎  ⏎ 03 ⏎  ⏎ 03 ⏎  ⏎ 03 ⏎  ⏎ 03 ⏎  ⏎ 03 ⏎  ⏎ 03 ⏎  ⏎ 03 ⏎  ⏎ 03 ⏎  ⏎ 03 ⏎  ⏎ ho ⏎  ⏎ 4… |
| 4 | surya | 90.4 | 1.1s | Tape 5/5 ⏎ 00 03 40 01 CMP ⏎ Okay. SECS LOGIC is CLOSED; SECS ARM are CLOSED; ⏎ LOGIC POWER is ON. ⏎ LMP ⏎ Okay. ⏎ 00 03 40 13 ⏎ CC ⏎ 17, Houston. You have a GO for T&D. ⏎ CDR ⏎ O… |
| 4 | llm | 92.0 | 7.8s | Tape 5/5 ⏎  ⏎ 00 03 40 01 CMP         Okay. SECS LOGIC is CLOSED; SECS ARM are CLOSED; ⏎                      LOGIC POWER is ON. ⏎  ⏎              LMP         Okay. ⏎  ⏎ 00 03 40 … |
| 5 | tesseract | 89.5 | 1.4s | Tape 46/4 ⏎  ⏎ o2 18 41 11 CDR ⏎  ⏎ CMP ⏎  ⏎ 02 18 41 59 +CMP ⏎ CDR ⏎ cc ⏎  ⏎ 02 18 42 34 CDR ⏎  ⏎ CC ⏎  ⏎ CDR ⏎  ⏎ cc ⏎ CDR ⏎  ⏎ CMP ⏎  ⏎ cc ⏎  ⏎ Okay. Is that it? Yes, I can get… |
| 5 | surya | 94.7 | 1.1s | Tape 46/4 ⏎ 02 18 41 11 ⏎ CDR ⏎ Okay. Is that it? Yes, I can get that, Gene. ⏎ CMP ⏎ Okay, you want to take a picture of it first? ⏎ Okay, POWER ... Okay, stand by. 3, 2, 1 - ⏎ 02… |
| 5 | llm | 92.0 | 9.2s | Tape 46/4 ⏎  ⏎ 02 18 41 11  CDR         Okay. Is that it? Yes, I can get that, Gene. ⏎  ⏎                 CMP         Okay, you want to take a picture of it first? ⏎              … |

### 4b68726be4af8ff9 — faded_fbi_scan
_FBI HQ-83894 Serial 220 (15 pp, mid-1950s carbon)_  (file: `65_hs1-834228961_62-hq-83894_serial_220.pdf`)

| Page | Engine | Conf | Wall-clock | Snippet |
|---:|---|---:|---:|---|
| 1 | tesseract | 27.0 | 1.9s | ym ben \| \| ⏎ c cWv ⏎  ⏎ VMN YUOUY NIH ice ⏎ AMMAN |
| 1 | surya | 90.9 | 1.5s | 62- ⏎ HQ-83894 ⏎ ENCL BEHIND FILE ⏎ Serials EBF 220 ⏎ EBF ⏎ 62-HQ-83894-EBF 220 ⏎ -220 ⏎ 438411 ⏎ 00 - ⏎ 0 ⏎ DO NOT<br>DESTROY ⏎ 1 19 ⏎ FOIPA# 1294932 ⏎ . ⏎ . ⏎ FBI - CENTRAL RECO… |
| 1 | llm | 75.0 | 4.4s | 62-                HQ-83894 ⏎  ⏎ Serials EBF 220 ⏎  ⏎ [BARCODE: EC-70-83894-EBF 220] ⏎                                                         EBF ⏎  ⏎                            … |
| 2 | tesseract | 93.0 | 3.7s | MIGUEL ANGEL GARCIA MACTIAS ⏎ Pianist Composer Discoverer ⏎ and Ideographic Inventor ⏎ No. 324 Pino Suarez Avenue ⏎  ⏎ VERACRUZ, Veracruz ⏎  ⏎ Veracruz, Veracruz ⏎ March 19, 1950 … |
| 2 | surya | 96.6 | 1.9s | . . ⏎ . . ⏎ MIGUEL ANGEL GARCIA MACIAS ⏎ Pianist Composer Discoverer ⏎ and Ideographic Inventor ⏎ No. 324 Pino Suarez Avenue ⏎ VERACRUZ, Veracruz ⏎ Veracruz, Veracruz ⏎ March 19, … |
| 2 | llm | 92.0 | 12.0s | MIGUEL ANGEL GARCIA MACIAS ⏎ Pianist Composer Discoverer ⏎ and Ideographic Inventor ⏎ No. 324 Pino Suarez Avenue ⏎ VERAGRUZ, Veracruz ⏎  ⏎                                         … |
| 3 | tesseract | 94.0 | 3.7s | «<2 = ⏎  ⏎ for eight months. After that time, and after I had paid all my fees as an ⏎ Inventor of the said Apparatus, I received a reply stating that the said ⏎ Patent had alread… |
| 3 | surya | 96.7 | 1.5s | . . ⏎ - 2 - ⏎ . ⏎ . ⏎ for eight months. After that time, and after I had paid all my fees as an ⏎ Inventor of the said Apparatus, I received a reply stating that the said ⏎ Patent… |
| 3 | llm | 92.0 | 12.2s | - 2 - ⏎  ⏎ for eight months. After that time, and after I had paid all my fees as an ⏎ Inventor of the said Apparatus, I received a reply stating that the said ⏎ Patent had alread… |
| 4 | tesseract | 95.2 | 1.9s | -3- ⏎  ⏎ the Water since the Conic-Global or Global-Conic form permits it. ⏎  ⏎ The force that the said apparatus can develop can be compared ⏎ only with THOUGHT since this has no… |
| 4 | surya | 92.7 | 1.2s | 4 ⏎ 10° 10° 10° 10° 10° 10° 10° 10° 10° 10°  ⏎ - 3 - ⏎ . . ⏎ the Water since the Conic-Global or Global-Conic form permits it. ⏎ The force that the said apparatus can develop can … |
| 4 | llm | 95.0 | 11.4s | - 3 - ⏎  ⏎ the Water since the Conic-Global or Global-Conic form permits it. ⏎  ⏎      The force that the said apparatus can develop can be compared ⏎ only with THOUGHT since this… |
| 5 | tesseract | 94.5 | 3.0s | THE FIRST PHOTOGRAPHS OF A "FLYING SAUCER", OBTAINED IN DURANGO AT AN ⏎ ALTITUDE OF 9000 FEET ⏎  ⏎ (Caption under photographs ) ⏎  ⏎ Mr. German Horacio Robles Jr., student at the … |
| 5 | surya | 94.8 | 1.7s | v 4 ⏎ 300 ⏎ THE FIRST PHOTOGRAPHS OF A "FLYING SAUCER", OBTAINED IN DURANGO AT AN ⏎ ALTITUDE OF 9000 FEET ⏎ (Caption under photographs) ⏎ Mr. German Horacio Robles Jr., student at… |
| 5 | llm | 92.0 | 10.2s | THE FIRST PHOTOGRAPHS OF A "FLYING SAUCER", OBTAINED IN DURANGO AT AN ⏎ ALTITUDE OF 9000 FEET ⏎  ⏎ (Caption under photographs) ⏎  ⏎ Mr. German Horacio Robles Jr., student at the N… |

### 15d23b5f88df64fa — multi_column_form
_DOW-UAP-D25 Mission Report Greece Jan 2024 (7 pp)_  (file: `dow-uap-d25-mission-report-greece-january-2024.pdf`)

| Page | Engine | Conf | Wall-clock | Snippet |
|---:|---|---:|---:|---|
| 1 | tesseract | 81.6 | 1.6s | Misrep undefined-9629373 ⏎  ⏎ Narrative ⏎ GReReneeeneana ⏎ AT 01092, (b)(1)1.4a CONDUCTED SLR TAKE OFF FROM LGLR. ®)")'48PROCEEDED TO ⏎  ⏎ FRAGGED TASKING TO SUPPORT ⏎ AT 0509Z, ®… |
| 1 | surya | 80.8 | 1.5s | Declassified by MG Richard A. Harrison ⏎ <b>USCENTCOM Chief of Staff</b> ⏎ Declassified on: 24 October 2025 ⏎ Misrep undefined-9629373 ⏎ <b>Narrative</b> ⏎ (SECRETIFIED TO USI, TV… |
| 1 | llm | 75.0 | 12.5s | Declassified by MG Richard A. Harrison ⏎ USCENTCOM Chief of Staff ⏎ Declassified on: 24 October 2025 ⏎  ⏎ [REDACTED] ⏎  ⏎ Misrep undefined-9629373 ⏎  ⏎ Narrative ⏎  ⏎ [REDACTED] ⏎… |
| 2 | tesseract | 85.4 | 1.3s | MSGID ⏎  ⏎ ¢ Report Type: MISREP ⏎ ¢ Originator (Unit or Squadron): 33 SOS ⏎ ¢ Submit Date: ⏎  ⏎ MSNID ⏎  ⏎ ¢ Tasking Order (ATO): 24-024 ⏎  ⏎ ¢ Mission Type: ISR ⏎  ⏎ ¢ ATO Missi… |
| 2 | surya | 85.9 | 1.1s | Declassified by MG Richard A. Harrison ⏎ <b>USCENTCOM Chief of Staff</b> ⏎ Declassified on: 24 October 2025 ⏎ CECDET/DEL TO LICA EVEN ⏎ <b>MSGID</b> ⏎ • <b>Report Type:</b> MISREP… |
| 2 | llm | 75.0 | 7.3s | Declassified by MG Richard A. Harrison ⏎ USCENTCOM Chief of Staff ⏎ Declassified on: 24 October 2025 ⏎  ⏎ [REDACTED] ⏎  ⏎ MSGID ⏎  ⏎ • Report Type: MISREP ⏎ • Originator (Unit or … |
| 3 | tesseract | 89.3 | 1.5s | ¢ Wing: Other ⏎ ¢ Phone Number Exemptibn (b)(6) ⏎ * Email:[_3.5c, FOIA Exemption (b)(6) \| ⏎  ⏎ ¢ Service: Air Force ⏎ ¢ Operations Center: 603 AOC ⏎  ⏎ INGEST ⏎  ⏎ ¢ Rank: ⏎  ⏎ Fu… |
| 3 | surya | 75.6 | 1.1s | Declassified by MG Richard A. Harrison ⏎ <b>USCENTCOM Chief of Staff</b> ⏎ Declassified on: 24 October 2025 ⏎ • Wing: Other ⏎ • Phone Numbero IA Exemption (b)(6) ⏎ • Email: ⏎ 3.5c… |
| 3 | llm | 85.0 | 6.5s | Declassified by MG Richard A. Harrison ⏎ USCENTCOM Chief of Staff ⏎ Declassified on: 24 October 2025 ⏎  ⏎ [REDACTED] ⏎  ⏎ • Wing: Other ⏎ • Phone Number: FOIA Exemption (b)(6) ⏎ •… |
| 4 | tesseract | 87.2 | 1.5s | ¢ Type of IR-Guided AAM: ⏎  ⏎ ¢ Num IR-Guided AAM: ⏎  ⏎ ¢ Gun Name or Designator: ⏎  ⏎ ¢ Num Gun Rounds: ⏎  ⏎ ¢ Air-to-Ground Wpn to Include Num of Each: - ⏎ ¢ TGT Pod Name or Des… |
| 4 | surya | 79.6 | 1.1s | Declassified by MG Richard A. Harrison ⏎ <b>USCENTCOM Chief of Staff</b> ⏎ Declassified on: 24 October 2025 ⏎ • Type of IR-Guided AAM: ⏎ • Num IR-Guided AAM: ⏎ • Gun Name or Desig… |
| 4 | llm | 85.0 | 8.5s | Declassified by MG Richard A. Harrison ⏎ USCENTCOM Chief of Staff ⏎ Declassified on: 24 October 2025 ⏎  ⏎ [REDACTED] ⏎  ⏎ • Type of IR-Guided AAM: ⏎ • Num IR-Guided AAM: ⏎ • Gun N… |
| 5 | tesseract | 87.3 | 1.7s | Off Station ⏎  ⏎ ¢ Time Off Station DTG: 251504:00ZJAN24 ⏎ ¢ Total Time On Station: 8 hours 29 minutes ⏎ ¢ Gentext/Additional Details: ⏎  ⏎ ISR ⏎  ⏎ Time-on Station DTG: 250635:00… |
| 5 | surya | 78.7 | 2.9s | Declassified by MG Richard A. Harrison ⏎ <b>USCENTCOM Chief of Staff</b> ⏎ Declassified on: 24 October 2025 ⏎ THE TO COME THE ⏎ Off Station ⏎ • Time Off Station DTG: 251504:00ZJAN… |
| 5 | llm | 75.0 | 10.0s | Declassified by MG Richard A. Harrison ⏎ USCENTCOM Chief of Staff ⏎ Declassified on: 24 October 2025 ⏎  ⏎ [REDACTED] ⏎  ⏎ Off Station ⏎  ⏎ • Time Off Station DTG: 251504:00ZJAN24 … |

### 26b02d358ec20061 — redacted_page
_FBI HQ-101634279 100-DE-26505 (15 pp, black-bar redactions)_  (file: `65_hs1-101634279_100-de-26505.pdf`)

| Page | Engine | Conf | Wall-clock | Snippet |
|---:|---|---:|---:|---|
| 1 | tesseract | 42.7 | 2.9s | FD-245 (REV. 1-21-80) ⏎  ⏎ Oddy ⏎  ⏎ 6d doo ⏎  ⏎ fee) ⏎ ~~ ⏎ i) ⏎ C ⏎ — ⏎ Le) ⏎ ™N ⏎ BSS ⏎ oi ⏎ Le) ⏎ » ⏎  ⏎ See ⏎ —___ ⏎ j—_—_,_ 4 ⏎ a ⏎ oo ⏎ Lncuemvaanmnsomtememsee } ⏎ = ⏎ ——— … |
| 1 | surya | 82.5 | 2.1s | FD-245 (REV. 1-21-80) ⏎ Screened by NARA (RF) ⏎ 11-19-2025 FOIA # ⏎ 30290 DOCID: 34714592 ⏎ II. S. Department of Instice ⏎ Declassification authority ⏎ derived from FBI Automatic … |
| 1 | llm | 65.0 | 6.7s | FD-245 (REV. 1-21-80) ⏎  ⏎ Screened by NARA [RF] ⏎ 11-19-2025 FOIA II ⏎ 90290 DOCID: 3471489 ⏎  ⏎ U. S. Department of Justice ⏎  ⏎ [MUST NOT BE REMOVED FROM OR ADDED TO THIS FILE]… |
| 2 | tesseract | 51.1 | 1.8s | 1. Notes re: interview with WLADYSLAW KRASUSKI (rec'd 11/7/57( ⏎  ⏎ ait. TNRORMATTGN CONTA: ⏎ we NA ee ee Se “ ⏎  ⏎ Loreen eo 3 i ⏎  ⏎ * PA k aaa Nw nw Om aE ⏎ atypr 2 coacr F Ty … |
| 2 | surya | 81.2 | 3.2s | Notes re: interview with WLADYSLAW KRASUSKI (rec'd 11/7/57( ⏎ 1. ⏎ TIL INFORMATION CONTAINED ON this envelope ⏎  ⏎ HEREIT JULIASSIFIED & Bjottey ⏎  ⏎ DATE 5/25/85 BY SP-6 Sportley… |
| 2 | llm | 75.0 | 4.4s | C                                                C ⏎  ⏎  ⏎ 1.  Notes re: interview with WLADYSLAW KRASUSKI (rec'd 11/7/57( ⏎  ⏎  ⏎  ⏎  ⏎  ⏎  ⏎  ⏎  ⏎  ⏎  ⏎  ⏎  ⏎  ⏎  ⏎  ⏎          … |
| 3 | tesseract | 14.9 | 10.6s | : _ ee . ⏎ . a : 2 ⏎ \| _ . : ⏎  ⏎ \| oe a So ⏎ . \| ⏎  ⏎ 1 . a ve Lee ⏎  ⏎ a a. J sees i ⏎  ⏎ 7 . o . " oo a ‘ ⏎ 3 L : ⏎  ⏎ C : oe ⏎  ⏎ ee . ) ⏎  ⏎ _ 2 : ⏎  ⏎ : Paes ⏎ : a oe ⏎  ⏎ o… |
| 3 | surya | 72.4 | 1.2s | 4947 ⏎ insk1 ⏎ 4 ⏎  ⏎  ⏎ W ⏎ 500 ⏎  ⏎ ASKOY. ⏎ j ⏎  ⏎ (Address of contributor) ⏎ (Name of Special Agent) ⏎ Returned Yes ( ) ⏎ 2620 ⏎ (Name of contributor) ⏎ 5 ⏎ X ⏎ 3 ⏎ b ⏎ E Rece… |
| 3 | llm | 45.0 | 5.2s | Date Received ________________ ⏎  ⏎ From _____________ (Name of contributor) ⏎          _____________ (Address) ⏎  ⏎ By _____________ (Initials of contributor) _______________ ⏎ T… |
| 4 | tesseract | 81.9 | 2.1s | “ga ⏎  ⏎ 2 ⏎  ⏎ GN CON ⏎  ⏎ ASoLFIED ⏎  ⏎ NW 90290 ⏎ Docld:34714592 Page 4 |
| 4 | surya | 61.6 | 3.2s | 11/7/57 ⏎ WARING AND CAMPAGE OF THE STATE OF THE STATE OF THE STATE OF THE STATE OF THE STATE OF THE STATE OF THE STATE OF THE STATE OF THE STATE OF THE STATE OF THE STATE OF THE … |
| 4 | llm | 35.0 | 5.2s | WA 27916 - 4/25/19 ⏎ 5457 go Compar ⏎  ⏎ per ⏎ cable sle sum in 44 ⏎ gods in 45 ⏎  ⏎ 400 ⏎  ⏎ [VARIOUS SKETCHES AND DIAGRAMS] ⏎  ⏎ $2 + 4/4 + 45 ⏎ [ILLEGIBLE] (S) + ⏎ 2-3) nu ⏎ Br… |
| 5 | tesseract | 81.8 | 1.7s | G 86eq Z6SPbLPE:PI20q \| ⏎ 06206 MN \| ⏎  ⏎ wr WLADYSLAW ERAS USK nl >\| ⏎  ⏎ two - DLTOS |
| 5 | surya | 84.1 | 1.4s | Docld:34714592 Page 5 ⏎ 06Z06 MN ⏎  ⏎  ⏎  ⏎ . . . . . . . . ⏎  ⏎  ⏎  ⏎ 网络医皮属 ⏎  ⏎  ⏎  ⏎  ⏎ 9.30 ⏎ Leternan ur beladyslan krasuski 11/7/59 ⏎ 100-26505 |
| 5 | llm | 35.0 | 4.3s | NM 06200 ⏎ DocID:P1:3065H:26:8 aBeG S ⏎  ⏎ [ILLEGIBLE TEXT WITH WATERMARKS] ⏎  ⏎ [ILLEGIBLE TEXT - appears to be "DIRECTOR OF INVESTIGATION CONTINUED" or similar] ⏎  ⏎ [PAGE CONTA… |

### 13f86e95aed52840 — long_debriefing
_FBI HQ-83894 Section 6 (271 pp, mixed-quality omnibus)_  (file: `65_hs1-834228961_62-hq-83894_section_6.pdf`)

| Page | Engine | Conf | Wall-clock | Snippet |
|---:|---|---:|---:|---|
| 1 | tesseract | 66.8 | 1.8s | g2- \|H0-49894 grin 6 ⏎ IAS 246-30! ⏎  ⏎ *62-HQ-83 \| \| ⏎  ⏎ Guide, issued May 24, 2007. ⏎  ⏎ 3 ⏎ > ⏎ = ⏎ ® ⏎ ue) ⏎ = ⏎ = ⏎ fe} ⏎ ss ⏎ =] ⏎ oO ⏎ i> ⏎ S ⏎ E ⏎ ” ⏎ wo ⏎ 3 ⏎  ⏎ from FB… |
| 1 | surya | 87.9 | 1.8s | 4-564 (12-22-55) ⏎ Declassification authority derived ⏎ 0062 ⏎ Class / Case # ⏎ from FBI Automatic Declassification ⏎ OH<br>OH ⏎ Guide, issued May 24, 2007. ⏎ SERIALS ⏎ R ⏎ 83894 … |
| 1 | llm | 65.0 | 6.8s | 4364 (1/22-23) ⏎  ⏎ [Document header with barcode and reference numbers] ⏎  ⏎ 81117241388 ⏎  ⏎ CASE #1 + HEADQUARTERS ⏎ FBI - CENTRAL RECORDS CENTER ⏎  ⏎ [Barcode/reference inform… |
| 2 | tesseract | 84.5 | 3.4s | Office Memordndum + onrrep states GOVERNMEN; ⏎ TO : Dp. rade DATE: August BV ⏎ FROM : Fen F Belietop™ a ⏎  ⏎ SUBJECT: SUMMARY er ⏎ PHENOMENA IN NEW MEXICO ⏎ i MISCELLANEOUS - INFO… |
| 2 | surya | 94.5 | 2.7s | STANDARD FORM NO. 64 ⏎ Office Memorandum • UNITED STATES GOVERNMENT ⏎ DATE: August 2. ⏎ TO ⏎ D. M. Ladd ⏎ A. H. Belmo ⏎ FROM ⏎ SUBJECT: ⏎ SUMMARY OF AERIAL ⏎ PHENOMENA IN NEW MEXI… |
| 2 | llm | 92.0 | 8.3s | STANDARD FORM NO. 64 ⏎  ⏎ Office Memorandum • UNITED STATES GOVERNMENT ⏎  ⏎ TO        :    D. M. Ladd                                DATE:    August 2, 1950 ⏎  ⏎ FROM      :    A.… |
| 3 | tesseract | 32.1 | 1.0s | 5USNF 40123 ⏎ Re ⏎ iNOWT38 0.934 ⏎  ⏎ 05. HY eo \|] § 43S |
| 3 | surya | 48.9 | 6.0s | TO ANY PARKETURAL PRINTS ⏎ ATTEMPORTURE TO STORY ⏎ DATE: CONTROL SAL LING ⏎ 5.50 L 38 . . . . . . . . . . . . . . . . . .  ⏎ THE ONL OF ⏎  ⏎ 2508,608 ⏎  ⏎  ⏎ THE RESERVE OF THE PR… |
| 3 | llm | 35.0 | 3.6s | SEP 5 1962 IN 50 ⏎ RECD BELMONT ⏎ F.B.I. ⏎ ENT-JUSTICE ⏎  ⏎  ⏎ [ILLEGIBLE TEXT - heavily faded typewritten content in center of page] ⏎  ⏎  ⏎ REFERRAL- ⏎ F.B.I. ⏎ REF-JUSTICE ⏎  ⏎… |
| 4 | tesseract | 92.6 | 3.9s | RESULTS OF AN INQUIRY BY PROFESSOR LINCOLN LA PAZ ⏎  ⏎ Dr. Lapaz, Director, Institute of Meteoritics, ⏎ University of New Mexico, submitted an analysis of the various ⏎ observatio… |
| 4 | surya | 96.2 | 1.3s | RESULTS OF AN INQUIRY BY PROFESSOR LINCOLN LA PAZ ⏎ Dr. LaPaz, Director, Institute of Meteoritics, ⏎ University of New Mexico, submitted an analysis of the various ⏎ observations … |
| 4 | llm | 92.0 | 8.6s | RESULTS OF AN INQUIRY BY PROFESSOR LINCOLN LA PAZ ⏎  ⏎ Dr. LaPaz, Director, Institute of Meteorites, ⏎ University of New Mexico, submitted an analysis of the various ⏎ observation… |
| 5 | tesseract | 92.0 | 1.8s | CONCLUSIONS ⏎  ⏎ The Albuquerque Office, in a letter dated August 10, ⏎ 1950, advised that there have been no new developments in connection ⏎ with the efforts to ascertain the id… |
| 5 | surya | 98.6 | 1.0s | CONCLUSIONS ⏎ The Albuquerque Office, in a letter dated August 10, ⏎ 1950, advised that there have been no new developments in connection ⏎ with the efforts to ascertain the ident… |
| 5 | llm | 88.0 | 4.5s | CONCLUSIONS ⏎  ⏎ The Albuquerque Office, in a letter dated August 10, ⏎ 1950, advised that there have been no new developments in connection ⏎ with the efforts to ascertain the id… |

---

_Generated by `scripts/build_ocr_report.py` from `ocr-20260509T002235Z.json`._
