# verki — AI-helpita tekstgenerado kaj reskribo

`verki` estas CLI-komando por generi, reskribi, kaj adapti tekston per AI. Ĝi subtenadas diversajn ĉefajn malvolontojn (tono, longo, registro) kaj permesas vi difini vian personan skribstilo.

## Superrigardo

`verki` havas du ĉefajn subkomandojn:
- `verki generi` — Generi aŭ reskribi tekston laŭ instrukcioj
- `verki modelo` — Elĉerpi disponeblajn modelojn de provizanto

## Setup

### Akiri Hugging Face API-ŝlosilon

1. Iru al [huggingface.co](https://huggingface.co)
2. Ensaluti aŭ krei konton
3. Iru al [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)
4. Klaku "New token" kaj kreu unu kun `read` aliroj
5. Kopiu la ŝlosilon

### Konservi ŝlosilon en uzanto profilo

**Aŭtomate** (rekomendite):
```bash
autish uzanto profilo modifi --api-slosilo-huggingface hf_xxxxx...
```

**Aŭtomate ĉe environ**:
Metu en bashrc/zshrc:
```bash
export HF_TOKEN="hf_xxxxx..."
# aŭ
export HUGGINGFACE_API_TOKEN="hf_xxxxx..."
```

**Inline** (sekureca averto):
```bash
verki generi -i "..." --api-slosilo hf_xxxxx...
```

## Ĉefa komando: `verki generi`

Generi aŭ reskribi tekston kun AI-asistado.

### Bazo — nenio:

```bash
verki generi -i "Kreu mallongan haŭton"
```

### Reskribi ekzistan tekston:

```bash
verki generi -i "Reskribu pli klare" -t "Malnova versio"
```

### Lexi tekston el dosiero:

```bash
verki generi -i "Reskribu pli formale" -td ./malneto.txt
```

### Specifi variaĵojn

**Tono** — Emoca koloro de la produkaĵo:
```bash
verki generi -i "..." -to "trankvila"
verki generi -i "..." -to "luma"
verki generi -i "..." -to "profesia"
```

**Longo** — Cela volumo:
```bash
verki generi -i "..." -lo mallonga
verki generi -i "..." -lo normala
verki generi -i "..." -lo longa
```

**Registro** — Lingva formaleco:
```bash
verki generi -i "..." -r "formala"
verki generi -i "..." -r "neformala"
```

**Personaĵa stilo** — Priskriboj aŭ proveoj:
```bash
verki generi -i "..." -s "simpla, rekta, klaraj frazoj"
verki generi -i "..." -se "Mi uzas mallongajn frazojn sen komplikitaj strukturoj."
verki generi -i "..." -sd ./mia_stilo.txt
```

### Aldona kunteksto

Transpasi dosieron kun agorda informo:
```bash
verki generi -i "..." -k ./kunteksto.md
```

Ekzempla `kunteksto.md`:
```
Aŭdienco: redaktisto de teknikan revuon
Amplekso: artikolo por blogo
Ĉefaj punktoj: klaro, aktualo, faktoj
```

### Ĉefaj parametroj

| Flago | Nomo | Priskribo | Defaŭlto |
|-------|------|----------|---------|
| `-i` | `--instrukcio` | **Deviga.** Kion fari. | — |
| `-t` | `--teksto` | Enhava teksto (aŭ `-td`). | neniuj |
| `-td` | `--teksto-dosiero` | Vojo al dosiero. | neniuj |
| `-to` | `--tono` | Tono (ekz. trankvila). | neniuj |
| `-lo` | `--longo` | mallonga \| normala \| longa | neniuj |
| `-r` | `--registro` | Formaleco. | neniuj |
| `-s` | `--stilo` | Priskribo de stilo. | neniuj |
| `-se` | `--stilo-ekzemplo` | Teksta stilo-provo. | neniuj |
| `-sd` | `--stilo-dosiero` | Vojo al dosiero kun stilo. | neniuj |
| `-k` | `--kunteksto-dosiero` | Vojo al aldona kunteksto. | neniuj |
| `-m` | `--modelo` | HF modelo ID. | google/flan-t5-base |
| `-p` | `--provizanto` | AI-provizanto. | huggingface |
| `-a` | `--api-slosilo` | API-ŝlosilo (se ne en profilo). | neniuj |
| `-mt` | `--maksimumaj-tokenoj` | Maksimuma novaĵo-logonoj. | 512 |
| `-tm` | `--temperaturo` | Kreema grado (0–2). | 0.7 |

## Subkomando: `verki modelo`

Elĉerpi disponeblajn modelojn de Hugging Face.

### Elĉerpi ĉiujn populara modeloj:

```bash
verki modelo
```

### Serĉi laŭ nomo:

```bash
verki modelo -n flan-t5
verki modelo -n "gpt2"
```

### Limigi rezultojn:

```bash
verki modelo -n flan -L 5
```

### Parametroj

| Flago | Nomo | Priskribo | Defaŭlto |
|-------|------|----------|---------|
| `-n` | `--nomo` | Ĉepi por serĉo. | neniuj (ĉiuj) |
| `-p` | `--provizanto` | AI-provizanto. | huggingface |
| `-a` | `--api-slosilo` | API-ŝlosilo (se ne en profilo). | neniuj |
| `-L` | `--limigo` | Maksimuma rezultoj. | 10 |

## Scribajn instrukcio en bona kvalito

**Ĉefo**: Esti preciza kaj konteksta.

### Ĝeneraj ekzemploj:

❌ Malbono:
```
verki generi -i "Pli bona"
```

✅ Bona:
```
verki generi -i "Reskribu pli klare kaj per mallongaj frazoj"
verki generi -i "Ĉanĝu en malprofesian, ĝojan tonom"
verki generi -i "Reduktu al unu alineon, tenante ĉiujn faktojn"
```

### Kombinaĵoj kaj konteksto:

```bash
# Formaligi raportojn
verki generi \
  -i "Reskribu en profesia teknikan lingvon" \
  -r formala \
  -lo normala \
  -td ./raporto.txt

# Reverkado ĉe neformala stilo
verki generi \
  -i "Reskribu en mia persona voĉo" \
  -s "direkta, amika, kun humoroj" \
  -se "Ĉi ĉi estas mi! Mi parolas per mallongaj frazoj." \
  -td ./originalajxo.txt

# Resumaĵo
verki generi \
  -i "Kreu mallongan resumaĵon (3–4 frazoj)" \
  -lo mallonga \
  -td ./dokumento.md
```

## Modeloj

Ĝi uzas [Hugging Face Inference API](https://huggingface.co/inference-api) por ĉera aliro al modeloj.

**Rekomendita por teksgenadoj**:
- `google/flan-t5-base` — Bone: rapida, kompetenta, bone por esperanto
- `google/flan-t5-large` — Pli preciza, pli malrapida
- `meta-llama/Llama-2-7b-chat` — Pli natura lingvo (se aliro disponas)

**Ser ĉepu modelon:**
```bash
verki modelo -n t5
```

Por pli detala ĝo sur disponablaj modeloj, vizitu [huggingface.co/models](https://huggingface.co/models?sort=downloads).

## Privateco kaj sekureco

- **Tokenoj estas ne sendataj al autish-servoroj**: Ĝi uzas rektajn HTTP-petojn al Hugging Face
- **Profilo-konservo**: Ĝi konservas ĝin en `~/.local/share/autish/` aŭ ĉifrita per `~/.local/share/autish/uzanto_profilo.enc`
- **Ĉifrais**: Agordu majstran pasvorton per `autish uzanto pasvorto` por ĉifri la profilon

## Eraroj kaj felsecoj

**"Mankas API-slosilo"**:
- Konservu en profilo: `autish uzanto profilo modifi -a hf_xxxxx`
- Aŭ metu en medio: `export HF_TOKEN="hf_xxxxx"`
- Aŭ transpasu inline: `verki generi -a hf_xxxxx ...`

**"Model loading failed"**:
- Modelo estas forĝinta aŭ neakcepta
- Certu ke ĝi ekzistas: `verki modelo -n <nomo>`
- Provu defaŭlton: `verki generi -i "..." -m google/flan-t5-base`

**Malrapida responso**:
- Unua aliro al modelo ĝin-ŝargas (30–60 sec normale)
- Hugging Face-a gratisa tavolo rajtas malveigi ĉe ĉuta kutimo
- Provu poste, aŭ uzu `meta-llama/Llama-2-7b-chat` (se aliro)

## Refoj

- [Hugging Face Inference API — Dokumento](https://huggingface.co/docs/api-inference)
- [HF Model Hub](https://huggingface.co/models?sort=downloads)
- [Esperanto Lingvoj](https://eo.wikipedia.org/wiki/Esperanto)
