# Dashboard iPerf3 Monitoring and Testing

Dashboard web untuk monitoring dan pengujian jaringan berbasis iPerf3 dengan arsitektur Python Flask + Flask-SocketIO.

## Ringkasan Fitur

- Realtime test TCP/UDP via WebSocket
- Start/Stop test iPerf3 dengan subprocess yang aman
- Pola sampling per siklus: iPerf3 -> ping -> ulang sampai auto-stop
- Monitoring throughput, transfer, jitter, packet loss, retransmit, ping
- Realtime chart dan terminal-style log viewer
- History: search, filter, sort, pagination, delete session
- Final report: ringkasan, chart, tabel semua data per sampel + waktu
- Export data: JSON, JSONL, CSV, XLSX (termasuk detail log)
- Penyimpanan lokal:
  - logs/test_logs.jsonl
  - data/history.json
  - data/sessions.json
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
|   `-- sessions.json
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
|   |   `-- history.js
|   `-- img/
|       `-- Logo_Unhan.png (atau file logo Anda)
`-- templates/
    |-- layout.html
    |-- index.html
    |-- history.html
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

## Alur Pengujian

Flow per sampling interval:

1. Jalankan iPerf3 selama N detik (sesuai sampling interval).
2. Parse hasil iPerf3.
3. Jalankan ping satu kali.
4. Simpan data metrik dan log.
5. Ulangi hingga auto-stop menit tercapai atau user menekan stop.

## Cara Pakai Dashboard

1. Isi form pengujian di halaman Dashboard.
2. Set protocol TCP/UDP.
3. Isi sampling interval (detik) dan auto-stop (menit).
4. Klik Start Test.
5. Pantau kartu statistik, chart realtime, dan log realtime.
6. Buka History untuk melihat daftar sesi.
7. Klik Detail untuk membuka Final Report.
8. Unduh hasil dari Final Report (Excel) atau endpoint export API.

## Endpoint API

### Test control

- POST /api/test/start
- POST /api/test/stop
- GET /api/status

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

## Lisensi

Digunakan untuk kebutuhan internal riset/operasional.
