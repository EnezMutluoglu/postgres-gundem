# Postgres Gündem

PostgreSQL’in güvenlik duyurularını, etkilenen ve düzeltilen sürümleri, geliştirme notlarını ve eklentileri Türkçe gösteren tek sayfalık bülten. Haber kaynakları saatte bir kontrol edilir. Etkilenen sürüm ve yama bilgisi PostgreSQL’in yayımladığı kayıtlardan okunur. Ağ bağlantısı kesildiğinde son bülten okunabilir.

## Hetzner’de Docker ile temiz kurulum

Varsayılan çevirmen TranslateGemma 4B Q4_K_M, 40 DBA cümlesinin 38'inde teknik ve dil denetimlerini geçti. Önceki Riva modeli aynı denetimlerin 28'ini geçti. [Örnek çeviriler ve 4B modellerin bellek ayarları](release/translation-report.md)

Linux ARM64 veya x86-64, Docker Engine ve Compose v2 gerekir. Kurucu sunucudaki Bash, Python 3.9+, OpenSSL 3, curl ve tar araçlarını kullanır. Model sunucunun işlemcisiyle çalışır. Ağırlıkları bellek eşleme ile açar ve bir seferde bir metin çevirir. Model ve SQLite yeni sürümlerde de aynı sunucu klasörlerinde kalır.

Root olarak aşağıdaki komutları çalıştırın. Adımlar ilk kararlı sürüme sabitlenmiştir. İndirdiğiniz kurulum paketinin özetini sürüm sayfasındaki değerle de karşılaştırabilirsiniz. [Kararlı sürüm](https://github.com/EnezMutluoglu/postgres-gundem/releases/tag/v1.0.0)

```bash
set -e
cd /root
mkdir -p postgres-gundem-kurulum
cd postgres-gundem-kurulum
url=https://github.com/EnezMutluoglu/postgres-gundem/releases/download/v1.0.0
curl -fLO "$url/kurulum.tar.gz"
curl -fLO "$url/kurulum.tar.gz.sha256"
sha256sum -c kurulum.tar.gz.sha256
tar -xzf kurulum.tar.gz
cd container
bash get-model.sh
bash install.sh docker
```

Modeli başka makinede indirdiyseniz `bash get-model.sh /root/model.gguf` kullanın. Betik özeti denetler. Kurucu yönetici parolasını terminalde iki kez sorar. Panelin, veritabanının ve modelin sağlık kontrollerini bekler. GHCR erişimi kısıtlandığında kurucu aynı imajın GitHub Release içindeki imzalı bildirimle doğrulanan kopyasını kullanır. Sunucuda model eğitimi veya derleme yapılmaz.

### Çalışan Hetzner panelinden geçiş

Eski kurulumda haber geçmişinizi korumak için yukarıdaki paketi açtıktan sonra `container` dizininde son iki komut yerine `bash hetzner-gecis.sh` çalıştırın. Model parçalarını önceden aktardıysanız `bash hetzner-gecis.sh /root/model-parcalari` kullanın. Betik önce modeli doğrular, eski servisleri durdurur, SQLite'ın doğrulanmış kopyasını ve aylık arşivleri aktarır. Yeni servisler sağlık kontrolünden geçince eski birimlerin otomatik başlangıcını kapatır. Ardından aşağıdaki Cloudflare rotasını değiştirin.

Eski uygulama ve haberler sırasıyla `/opt/postgres-gundem` ve `/var/lib/postgres-gundem` altında kalır. Alan açmadan önce yeni panelden haber geçmişini ve tünelden erişimi kontrol edin. Eski köprü gerekiyorsa `172.17.0.1:18080` adresiyle önceki kurulum için kullanılabilir. Geçiş yarıda kaldıysa betik hedef veritabanının üzerine yazmaz. Hatanın nedenini giderip kopya üzerinden devam etmek için eski servisleri durdurduktan sonra aynı dizinde `bash install.sh docker` çalıştırabilirsiniz.

### Modeli dosyadan kurma

Çevrimdışı model kurulumu için sürüm sayfasındaki `model.gguf.part-00`, `model.gguf.part-01` ve `model-parts.sha256` dosyalarını aynı klasöre aktarın. Bu klasörde `sha256sum -c model-parts.sha256` çalıştırın. Kurulum dizininde `bash get-model.sh /root/model-parcalari` parçaları birleştirip modelin tamamını doğrular. Model Google TranslateGemma'nın GGUF uyarlamasıdır. [Model, dönüştürme bilgisi ve lisans](https://huggingface.co/Menterium/translategemma-4b-it-GGUF/tree/d1709f49e90452b9189e0144cc6826d199616921)

### Cloudflare Tunnel

Mevcut tüneli kullanın. `docker ps --format '{{.Names}}  {{.Image}}'` ile sunucuda çalışan bağlayıcı konteynerini bulun. Aşağıdaki komutta adı kendi çıktınızla değiştirin.

```bash
docker network connect postgres-gundem-origin BAGLAYICI_KONTEYNER_ADI
docker run --rm --network postgres-gundem-origin curlimages/curl:8.12.1 \
  -fsS http://postgres-gundem:8080/health/ready
```

Bağlayıcının mevcut Compose dosyasında aşağıdaki ağı **mevcut ağları koruyarak** bağlayıcı servisine ekleyin. Bağlayıcı başka bir konteynerin ağ alanını paylaşıyorsa ağı o alanın sahibi olan servise ekleyin. Böylece bağlayıcı yeniden oluşturulunca panelin ismini çözebilir.

```yaml
services:
  cloudflared:
    networks:
      - default
      - postgres-gundem-origin
networks:
  postgres-gundem-origin:
    external: true
```

Cloudflare’da mevcut tünelin **Published application** rotasını düzenleyin. **Type** için `HTTP`, adres için `postgres-gundem:8080` girin. Panel ve model host üzerinde port yayımlamaz. Model servisi internete çıkışı kapalı ağda çalışır. [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/)

### Durum, disk ve geri dönüş

```bash
docker ps --filter name=postgres-gundem
docker logs --tail 30 postgres-gundem-updater
du -sh /srv/postgres-gundem/{data,arsiv,models,manager}
```

**Ayarlar** ekranında yerel yönetici parolasıyla oturum açın. Son taramayı, model durumunu, bekleyen çevirileri, arşivi ve kullanılabilir alanı görebilirsiniz. **Şimdi denetle** GitHub'daki son kararlı sürümü sorgular. **Güncelle** seçilen sürümü doğrular ve kurar. Panelin üzerinden Docker veya Podman komutu çalıştırılamaz. Tarayıcı çerezleri HTTPS gerektirir.

| Sunucu klasörü | İçerik |
| --- | --- |
| `data/` | SQLite veritabanı ve WAL dosyaları |
| `arsiv/` | Ayın ilk günü 03.15 UTC sonrasında alınan sıkıştırılmış arşivler, son üç ay |
| `models/` | Salt okunur yerel model ağırlıkları |
| `manager/` | Etkin ve önceki sürüm, geri dönüş kopyası, kesintiye karşı işlem kaydı |
| `config/` | Yönetici parolasının özeti ve oturum anahtarı |

Güncellemede önce imaj ve model doğrulanır. Panel kısa süre durdurulur, SQLite’ın tutarlı kopyası alınır ve yeni sürüm başlatılır. Sağlık kontrolü başarısızsa önceki imajla ilişkili veritabanı geri yüklenir. Başarılı bir geçişi daha sonra elle geri aldığınızda veriler önceki geçiş anına döner.

Docker kurulumunda gerektiğinde SSH üzerinden önceki sürüme dönün.

```bash
(
  set -eu
  export PG_ROOT=/srv/postgres-gundem
  docker stop postgres-gundem-updater
  trap 'docker start postgres-gundem-updater >/dev/null' EXIT
  python3 "$PG_ROOT/controller/controller.py" rollback
)
```

Parolayı yenilemek için `python3 /srv/postgres-gundem/controller/admin-password.py` çalıştırın, ardından `docker restart postgres-gundem-web-1` ile web hizmetini yeniden başlatın.

## Podman ve Quadlet

RHEL ailesinde Podman **5.4+**, Quadlet, systemd, cgroup v2, Python 3.9+ ve OpenSSL 3 kullanın. Sistem düzeyindeki kurulumda yukarıdaki paketi root olarak açın ve son komutta `bash install.sh podman` çalıştırın. Servisler `postgres-gundem-web.service`, `postgres-gundem-model.service` ve `postgres-gundem-updater.service` olarak görünür.

Rootless kurulumda yönetici önce hizmet kullanıcısına alt UID/GID aralığı tanımlar ve `loginctl enable-linger KULLANICI` çalıştırır. Bu kullanıcıyla SSH oturumu açıp paketi kendi ev dizininde açın. Aynı kullanıcı olarak `bash get-model.sh` ve `bash install.sh podman` çalıştırın. Kalıcı klasör `~/.local/share/postgres-gundem` olur. `systemctl --user status postgres-gundem-web postgres-gundem-model postgres-gundem-updater` ile durumu inceleyin. Tunnel bağlayıcısı aynı kullanıcının Podman ağına bağlanmalıdır. SELinux etiketleri yalnızca projeye ayrılmış bind mount dizinlerinde ayarlanır.

Podman'da elle geri dönüş için ilgili düzeyde `postgres-gundem-updater` hizmetini durdurun, `PG_ROOT` değerini kurulum klasörüne ayarlayın ve `python3 "$PG_ROOT/controller/controller.py" rollback` çalıştırın. Ardından güncelleme hizmetini başlatın. Rootless kurulumda systemctl komutlarına `--user` ekleyin.

## Yeni sürüm yayımlama

`VERSION` ve `release/notes.txt` dosyalarını güncelleyin. Seçilen modelin sabit adresi ve özeti `deploy/container/model.json` içindedir. Testleri çalıştırıp karşılık gelen `vX.Y.Z` Git etiketini gönderin. GitHub Actions iki mimariyi kendi mimarisinde derler, test eder, GHCR imajlarını ve sürüm dosyalarını yayımlar. İmzalama anahtarı Actions sırrı `RELEASE_SIGNING_KEY` içindedir. Kurucu public anahtarı taşır. Güncelleyici, sabit depo ve anahtarla doğrulanmış sürüm bildirimindeki imaj kimliklerini kullanır.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
docker build -t postgres-gundem:local .
```

Panel kodu MIT lisanslıdır. Modelin üreticisi, kullanım koşulları ve dosya özeti model bildirimindedir. Yazı tiplerinin lisansları `static/fonts` altında bulunur. Fil logosu PostgreSQL projesine aittir. [PostgreSQL görsel kaynakları](https://www.postgresql.org/about/press/)

