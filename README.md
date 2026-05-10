# Dashboard iPerf3 Monitoring and Testing

Dashboard web untuk monitoring dan pengujian jaringan berbasis iPerf3 dengan arsitektur Python Flask + Flask-SocketIO.

## Ringkasan Fitur

- Dashboard Monitoring Realtime fokus untuk observasi metrik realtime
- Start/Stop test iPerf3 via API dan via Scheduler otomatis
- Pola sampling per siklus: iPerf3 -> ping -> ulang sampai auto-stop
- Monitoring throughput, transfer, jitter, packet loss, retransmit, ping
- Realtime chart dan terminal-style log viewer
- Sidebar statis (tidak ikut scroll) + jam realtime + indikator koneksi websocket
- Schedule: create, edit, delete task, dan eksekusi pada tanggal/jam tertentu
- History: search, filter, sort, pagination, delete session
- Final report: ringkasan, chart, tabel semua data per sampel + waktu
- Export data: JSON, JSONL, CSV, XLSX (termasuk detail log)
- Validasi unik: nama task/nama pengujian tidak boleh sama dengan nama pengujian di history
- Penyimpanan lokal:
  - logs/test_logs.jsonl
  - data/history.json
  - data/sessions.json
  - data/schedules.json
- Kompatibel Windows 10/11 dan Ubuntu Linux

## Teknologi

- Python 3.12+
- Flask
- Flask-SocketIO
- Bootstrap 5
- Chart.js
- Vanilla JavaScript
- JSON/JSONL file storage

## Struktur Project

```text
dashboard-ipsec/
|-- app.py
|-- config.json
|-- requirements.txt
|-- README.md
|-- data/
|   |-- history.json
|   |-- sessions.json
|   `-- schedules.json
|-- logs/
|   |-- test_logs.jsonl
|   |-- runtime.log
|   `-- error.log
|-- modules/
|   |-- exporter.py
|   |-- iperf_runner.py
|   |-- logger.py
|   |-- parser.py
|   |-- ping_monitor.py
|   |-- schedule_manager.py
|   |-- session_manager.py
|   |-- statistics.py
|   |-- utils.py
|   `-- __init__.py
|-- static/
|   |-- css/
|   |   `-- style.css
|   |-- js/
|   |   |-- charts.js
|   |   |-- dashboard.js
|   |   |-- history.js
|   |   `-- schedule.js
|   `-- img/
|       `-- Logo_Unhan.png (atau file logo Anda)
`-- templates/
    |-- layout.html
    |-- index.html
    |-- history.html
    |-- schedule.html
    `-- report.html
```

## Prasyarat

- Python 3.12 atau lebih baru
- iPerf3 tersedia di PATH
- Perintah ping tersedia di sistem

Verifikasi cepat:

```powershell
python --version
iperf3 --version
```

## Instalasi Windows 10/11

1. Buka PowerShell di folder project.
2. Buat virtual environment:

```powershell
python -m venv venv
```

3. Aktifkan virtual environment:

```powershell
venv\Scripts\Activate.ps1
```

4. Install dependency:

```powershell
pip install -r requirements.txt
```

5. Jalankan aplikasi:

```powershell
python app.py
```

6. Buka browser:

```text
http://127.0.0.1:5000
```

## Instalasi Ubuntu Linux

1. Install paket sistem:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip iperf3
```

2. Buat dan aktifkan virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
```

3. Install dependency dan jalankan app:

```bash
pip install -r requirements.txt
python app.py
```

4. Buka:

```text
http://127.0.0.1:5000
```

## Konfigurasi Utama

Konfigurasi berada di config.json.

Field penting:

- host, port: alamat server Flask
- defaults.tcp / defaults.udp: default parameter test
- defaults.auto_stop_minutes: default lama pengujian
- brand.campus_name / brand.student_name / brand.logo_path: branding sidebar
- data_paths.schedules: lokasi penyimpanan task scheduler

## Alur Pengujian

Flow per sampling interval:

1. Jalankan iPerf3 selama N detik (sesuai sampling interval).
2. Parse hasil iPerf3.
3. Jalankan ping satu kali.
4. Simpan data metrik dan log.
5. Ulangi hingga auto-stop menit tercapai atau user menekan stop.

## Cara Pakai Dashboard

1. Buka halaman Dashboard untuk monitoring realtime.
2. Pantau kartu statistik, chart realtime, panel task aktif, dan log realtime.
3. Gunakan tombol Stop Test jika ada test/task yang sedang berjalan.
4. Gunakan tombol Refresh Data untuk sinkronisasi status terbaru.

## Cara Pakai Schedule

1. Buka menu Schedule.
2. Isi Form Task pengujian (host, protocol, sampling, auto-stop, dan parameter lain).
3. Atur tanggal dan jam eksekusi.
4. Klik Simpan Task.
5. Task akan berjalan otomatis saat waktu jadwal tercapai.
6. Anda bisa edit/hapus task selama belum running.

Catatan validasi nama:

- Nama task dan nama pengujian akan ditolak jika sama dengan nama pengujian yang sudah ada di history.

## Endpoint API

### Test control

- POST /api/test/start
- POST /api/test/stop
- GET /api/status

### Schedule

- GET /api/schedules
- POST /api/schedules
- PUT /api/schedules/<task_id>
- DELETE /api/schedules/<task_id>

### Log and history

- POST /api/logs/clear
- GET /api/history
- GET /api/session/<session_id>
- DELETE /api/session/<session_id>

### Export

- GET /api/export?format=json
- GET /api/export?format=jsonl
- GET /api/export?format=csv
- GET /api/export?format=xlsx

Filter yang didukung export/history:

- protocol
- test_name
- host
- date
- session_id

Catatan export:

- File export sekarang menyertakan detail log/sampel, bukan hanya ringkasan history.

## Menjalankan di Production (opsional)

Install waitress:

```powershell
pip install waitress
```

Jalankan:

```powershell
waitress-serve --host=0.0.0.0 --port=5000 app:app
```

Gunakan reverse proxy (Nginx/Caddy) untuk TLS dan hardening.

## Troubleshooting

### python app.py exit code 1

Langkah cek:

1. Pastikan virtual environment aktif.
2. Pastikan dependency terpasang ulang:

```powershell
pip install -r requirements.txt
```

3. Verifikasi import:

```powershell
python -c "import app; print('ok')"
```

4. Jalankan lagi dan cek error terminal secara penuh.

### iPerf3 tidak terdeteksi

- Pastikan iperf3 --version berhasil.
- Jika baru install di Windows, restart terminal.

### Export XLSX gagal

- Pastikan openpyxl terinstall:

```powershell
pip install openpyxl
```

### Host invalid

- Gunakan IP/domain yang bisa di-resolve dari mesin server.

### Nama task/pengujian ditolak

- Jika muncul error nama sudah ada di history, gunakan nama task/pengujian yang berbeda.

## Lisensi

Digunakan untuk kebutuhan internal riset/operasional.
