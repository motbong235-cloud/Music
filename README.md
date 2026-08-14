# Kairozen Song Search Bot

Bot ស្វែងរក និងទាញយកចម្រៀងតាមចំណងជើង តាមរយៈ Telegram (ភាសាខ្មែរ)។

## មាតិកា package

```
song_search_bot.py   -> កូដ Bot ចម្បង
requirements.txt     -> Python dependencies
Dockerfile            -> សម្រាប់ deploy លើ Render ជាមួយ ffmpeg
render.yaml           -> Render Blueprint (រួមទាំង Persistent Disk)
.gitignore
README.md             -> ឯកសារនេះ
```

## របៀប Deploy លើ Render (ជំហានលម្អិត)

### ជម្រើសទី១ - ប្រើ Blueprint (`render.yaml`) [ណែនាំ]

1. Upload ទាំង folder នេះទៅ GitHub repository
2. លើ Render Dashboard → **New** → **Blueprint**
3. ភ្ជាប់ repository → Render នឹងអាន `render.yaml` ស្វ័យប្រវត្តិ
   (រួមទាំង Persistent Disk `/data` ដែលបានកំណត់រួច)
4. Render នឹងសួររក Environment Variables ដែលសម្គាល់ `sync: false`:
   - `BOT_TOKEN` — Token ពី @BotFather
   - `YOUTUBE_API_KEY` — Key ពី Google Cloud Console
5. ចុច **Apply** → Render នឹង build និង deploy ស្វ័យប្រវត្តិ (រួមទាំង ffmpeg តាម Dockerfile)

### ជម្រើសទី២ - បង្កើត Web Service ដោយដៃ

1. **New** → **Web Service** → ភ្ជាប់ GitHub repo
2. Environment: **Docker** (Render នឹងប្រើ `Dockerfile` ស្វ័យប្រវត្តិ)
3. បន្ថែម Environment Variables:
   - `BOT_TOKEN`
   - `YOUTUBE_API_KEY`
   - `DATA_DIR` = `/data`
4. **សំខាន់បំផុតសម្រាប់មិនបាត់ទិន្នន័យ:** ទៅ tab **Disks** → **Add Disk**:
   - Name: `song-bot-data`
   - Mount Path: `/data`
   - Size: 1 GB (គ្រប់គ្រាន់)
5. Save → Deploy

## ហេតុអ្វីត្រូវការ Persistent Disk?

លំនាំដើម Render Web Service មាន filesystem ជា **ephemeral** — មានន័យថារាល់ពេល
redeploy (push code ថ្មី, restart service) ទិន្នន័យទាំងអស់ក្នុង container នឹង **បាត់ស្រឡះ**។

Bot នេះរក្សាទុកស្ថិតិការប្រើប្រាស់ (`/stats`) ជា file `stats.json` នៅក្នុង
`DATA_DIR` (`/data`)។ បើគ្មាន Persistent Disk ភ្ជាប់ទៅ mount path នេះ ស្ថិតិនឹង
reset ទៅសូន្យរាល់ពេល update កូដ។ នៅពេលមាន Persistent Disk ភ្ជាប់រួច ទិន្នន័យក្នុង
`/data` នឹងបន្តស្ថិតនៅដដែល ទោះបីជា redeploy ប៉ុន្មានដងក៏ដោយ។

**ចំណាំ:** file mp3 ដែលទាញយកបណ្តោះអាសន្ន (`/tmp`) មិនត្រូវរក្សាទុកជាអចិន្ត្រៃយ៍ទេ
(លុបស្វ័យប្រវត្តិក្រោយផ្ញើ ៣០វិនាទី) ដូច្នេះមិនចាំបាច់ដាក់ក្នុង Persistent Disk។

## Environment Variables ទាំងអស់

| ឈ្មោះ | ចាំបាច់ | ពិពណ៌នា |
|---|---|---|
| `BOT_TOKEN` | ✅ | Token ពី @BotFather |
| `YOUTUBE_API_KEY` | ✅ | Key ពី Google Cloud Console (YouTube Data API v3) |
| `DATA_DIR` | ស្រេចចិត្ត (default `./data`) | Path ទៅ Persistent Disk |
| `YTDLP_COOKIES_FILE` | ស្រេចចិត្ត | Path ទៅ cookies.txt ជួយកាត់បន្ថយការចាប់ពេលទាញយក |

## ការធ្វើតេស្តលើ Termux (មុន deploy)

```bash
pip install -r requirements.txt --break-system-packages
export BOT_TOKEN="your_token"
export YOUTUBE_API_KEY="your_key"
python song_search_bot.py
```
