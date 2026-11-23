# Debian ARM64 kurulumu

**Yeni kurulum ve yükseltme için** Debian 12 ve 13'te model dahil `postgres-gundem-debian12-13-arm64.tar` kullanın. Kurulum, arşiv ve Docker içindeki Cloudflare Tunnel bağlantısı [ortak kurulum kılavuzunda](README.md) yer alır. Aşağıdaki adımlar önceki paketleri kullanan kurulumların onarımı içindir.

## Debian 12 (Bookworm) için onarım

Önce `cat /etc/os-release`, `dpkg --print-architecture` ve `getconf GNU_LIBC_VERSION` ile sistemi kontrol edin. Debian 12 ARM64 ve glibc 2.36 üzerinde `GLIBC_2.38` veya `GLIBCXX_3.4.32` hatası, eski paketteki motorun bu sistemde yüklenemediğini gösterir.

Bilgisayarınızdaki `paket` klasöründen **güncel** `onar-arm64.sh` ve `postgres-gundem-debian12-arm64-onarim.tar.gz` dosyalarını sunucuya gönderin. İkinci dosya Bookworm ile derlenmiş ARM64 motorunu, paneli ve servisleri içerir. Modelin kurulu kopyası SHA-256 ile doğrulanır. Gerekirse `/root/postgres-gundem-debian-arm64.tar` içindeki model kullanılabilir. Bu büyük arşivi onarım tamamlanana kadar saklayın.

```powershell
scp .\onar-arm64.sh .\postgres-gundem-debian12-arm64-onarim.tar.gz root@sunucu:/root/
```

Debian sunucusunda root olarak çalıştırın:

```bash
bash /root/onar-arm64.sh
```

Betik çalışma zamanı bağımlılıklarını kurar, paneli ve modeli başlatır, ikisinin HTTP yanıtını kontrol eder ve aylık arşiv zamanlayıcısını etkinleştirir. Beklenen çıktılar arasında `Panel HTTP 200` ve modelden `{"status":"ok"}` bulunur.

## Debian 13 (Trixie) için tam paket

`postgres-gundem-debian-arm64.tar` hem GGUF modelini hem de llama.cpp b12532'nin hazır ARM64 CPU motorunu içerir. Sunucuda derleme yapılmaz. Debian ve Python çalışma zamanı bağımlılıklarının kurulumu ve haberlerin alınması için internet gerekir.

## Dosyaları gönderin

Debian sunucusunda `dpkg --print-architecture` çıktısı `arm64` olmalı. `df -hT / /var/tmp /opt` ile boş alanı, `free -h` ile belleği kontrol edin. Arşiv, açılmış dosyalar ve kurulu model aynı bölümdeyken yaklaşık 8,4 GB tutar. Kurulum için yaklaşık 10 GB boş alan ayırın. Yerel çeviri için 8 GB RAM önerilir.

Temiz Debian 13.8 ARM64 testinde geçici dosyalar hariç `/opt/postgres-gundem` altında 2,82 GB ölçüldü. Bunun 2,76 GB'ı modeldir. GCC, Make ve CMake kurulmadı. İşletim sistemi, sistem günlükleri ve haber veritabanı bu ölçümün dışındadır.

Windows'ta `paket` klasöründe PowerShell açıp kendi SSH adresinizle çalıştırın. Debian 13'te büyük yüklemeler için disk üzerindeki `/var/tmp` uygundur.

```powershell
scp .\postgres-gundem-debian-arm64.tar .\postgres-gundem-debian-arm64.tar.sha256 kullanici@sunucu:/var/tmp/
ssh kullanici@sunucu
```

## Kurun ve geçici kopyaları kaldırın

Aşağıdaki bloğu Debian'da çalıştırın. Dosyaları `/tmp` içine gönderdiyseniz ilk `cd` satırını ona göre değiştirin. Root olarak bağlandıysanız `sudo` sözcüğünü kaldırabilirsiniz. Bilgisayarınızdaki paketi saklayın.

```bash
(
  set -eu
  cd /var/tmp
  paket=postgres-gundem-debian-arm64.tar
  test "$(dpkg --print-architecture)" = arm64
  sha256sum -c "$paket.sha256"
  calisma=$(mktemp -d /var/tmp/postgres-gundem.XXXXXXXX)
  trap 'rm -rf -- "$calisma"' EXIT
  tar -xf "$paket" -C "$calisma"
  sudo env TMPDIR=/var/tmp bash "$calisma/postgres-gundem/install.sh" --paketten
  systemctl is-active postgres-gundem postgres-gundem-model
  curl -fsS -o /dev/null -w 'Panel HTTP %{http_code}\n' http://127.0.0.1:8080/
  curl -fsS --retry 300 --retry-all-errors --retry-delay 2 http://127.0.0.1:18081/health
  rm -- "$paket" "$paket.sha256"
)
```

Beklenen çıktılar iki `active` satırı, `Panel HTTP 200` ve model için `{"status":"ok"}`. Sunucuya yüklediğiniz iki dosya sağlık kontrolleri geçince silinir. Geçici açma dizini blok sona erdiğinde temizlenir. Python ortamı, model ve çalışma zamanı kütüphaneleri `/opt/postgres-gundem` altında kalır. Sunucuda başka projelerin kullandığı paketlere temizlik uygulanmaz. Cloudflare Tunnel aynı sunucudaysa hedefi `http://127.0.0.1:8080` olarak ayarlayın.

## Haberlerin kullandığı alan

Haberler, sürüm bilgileri ve yerel çeviriler `/var/lib/postgres-gundem/gundem.sqlite` dosyasındadır. Aynı haberin içeriği değişince kaydı güncellenir. Model dosyası ayrı tutulur.

| Ölçülen örnek | Canlı SQLite verisinin tutarlı kopyası | Aynı kopya gzip ile |
| --- | ---: | ---: |
| 208 kayıt, model çevirileri başlamadan | 264 KiB | 45 KiB |
| 273 kayıt ve önbellekte 391 tamamlanmış metin çevirisi | 528 KiB | 111 KiB |

Bu iki örnek belirli veri kümeleridir. Aylık haber sayısı ve metin uzunluğu değişir. Kendi sunucunuzda haberlerin güncel boyutunu (varsa SQLite WAL ve SHM dosyaları dahil) ve uygulamanın ayrı boyutunu şu şekilde ölçebilirsiniz:

```bash
sudo sh -c 'du -ch /var/lib/postgres-gundem/gundem.sqlite*'
sudo du -sh /opt/postgres-gundem
```

## İsteğe bağlı aylık sıkıştırılmış arşiv

Arşiv varsayılan olarak kapalıdır. Etkinleştirmek ve ilk kopyayı hemen almak için çalıştırın:

```bash
sudo systemctl enable --now postgres-gundem-arsiv.timer
sudo systemctl start postgres-gundem-arsiv.service
systemctl list-timers --all postgres-gundem-arsiv.timer
sudo ls -lh /var/lib/postgres-gundem/arsiv/
```

Her ayın 1'inde 03.15 UTC'de (Türkiye saatiyle 06.15) panel çalışırken SQLite'ın çevrimiçi yedekleme API'siyle tutarlı kopya alınır, doğrulanır ve gzip ile sıkıştırılır. Aynı ay yeniden çalıştırılırsa o ayın kopyası yenilenir. Son üç ay dosyası tutulur. Boş veritabanı veya başarısız yedek yüzünden tamamlanmış arşivler silinmez. Arşiv yalnızca haber veritabanını içerir. Canlı haber geçmişinin tamamı panelde okunabilir kalır. Bu ayar ek bir kopya için yer kullanır. Sunucunun disk arızasına karşı koruma istiyorsanız bir kopyayı başka makinede saklayın.

Zamanlamayı kapatmak için `sudo systemctl disable --now postgres-gundem-arsiv.timer` kullanabilirsiniz. Arşivleri ayrı bir dizinde açmak için örnek:

```bash
sudo gzip -dc /var/lib/postgres-gundem/arsiv/gundem-YYYY-AA.sqlite.gz > "$HOME/gundem-geri-yukleme.sqlite"
```
