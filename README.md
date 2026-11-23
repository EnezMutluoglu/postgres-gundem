# Postgres Gündem

PostgreSQL’in güvenlik duyurularını, etkilenen ve düzeltilen sürümleri, geliştirme notlarını ve eklentileri Türkçe gösteren tek sayfalık bülten. Haber kaynakları saatte bir kontrol edilir. Etkilenen sürüm ve yama bilgisi PostgreSQL’in yayımladığı kayıtlardan okunur. Ağ bağlantısı kesildiğinde son bülten okunabilir.

**Dış basın** sekmesi yayıncı, özgün dil ve tarihle birlikte topluluk haberlerini gösterir. İlk açılışta ve ardından yedi günde bir doğrudan yayın akışları, PostgreSQL topluluğunun iki kaynak dizini, Planet ve 18 bölgesel Google Haberler araması taranır. Her görevin zamanı SQLite’a kaydedilir. Başarısız olan görev bir saat sonra yeniden denenir. Arama sonuçlarındaki yeni yayıncılar aday listesine girer. Haber yayımlamak için yayıncının bilinen kaynaklar veya topluluk dizinleriyle eşleşmesi gerekir. Dizinlerden çıkan yayıncılar için üç haftalık doğrulama süresi vardır. [Planet kaynak dizini](https://planet.postgresql.org/feeds.html) · [Uluslararası topluluklar](https://www.postgresql.org/community/international/)

Başlangıç kaynakları arasında Crunchy Data, CYBERTEC, CloudNativePG, Dalibo, PostgreSQL Europe, JPUG, ITPUG, PostgreSQL Türkiye ve Fransızca Planète ağı bulunur. Yerel model başlığı ve akış özetini kaynak dilinden Türkçeye çevirir. Kaynağın sağladığı özgün metin, yayın adresi ve sonraki değişiklikler SQLite’ta kalır. Çeviri hazırlanırken veya teknik doğrulama başarısız olduğunda özgün metne erişilebilir. Haber akışında yalnız başlık varsa panel yalnız başlığı sunar. [Crunchy Data](https://www.crunchydata.com/blog) · [Planète PostgreSQL](https://www.postgresql.fr/planete) · [JPUG](https://www.postgresql.jp/)

SQLite her haberin özgün metnini ve doğrulanan Türkçe başlığını, özetini ve gövde bölümlerini birlikte saklar. Aynı kaynak dilindeki aynı metin başka bir haberde veya yeni revizyonda geçerse kayıtlı Türkçesi kullanılır. Bir bölüm değişirse yalnız o bölüm yeniden çevrilir. Eski kurulumun mevcut çevirileri ilk açılışta çeviri belleğine alınır.

Sorunlu bölüm özgün dilinde okunabilir. SQLite bu bölüm için son hatayı, deneme sayısını, son deneme zamanını ve sonraki denemenin zamanını saklar. İlk iki hatadan sonra 2 ve 15 dakika beklenir. Üçüncü hatadan sonra bölüm sorunlu olarak işaretlenir ve yedi gün sonra yeniden denenir. Model bağlantısı kesilirse deneme hakkı korunur. **Ayarlar** bölümünde kayıtlı çeviri sayısı ve sonraki sorunlu çeviri denemesi görünür. **Çevirileri yeniden dene** düğmesi bu denemeyi öne alır.

**Haber arama** kutusuna bir kelime, sürüm, CVE numarası veya SQL tanımlayıcısı yazın. Bülten ve dış basın kayıtları, eski sürümleri, özgün metinleri ve yerel Türkçe çevirileriyle aranır. Arama eşleşen bölümü gösterir ve o tarihte kaydedilen yerel makaleyi açar. Model başlık ve özetlerden sonra akışların sağladığı uzun metinleri parça parça çevirir. Yeni çeviriler hazır oldukça arama dizinine girer. Yalnız başlık sunan yayınlar için arşivde başlık ve kaynak bağlantısı bulunur.

**Haberlerin zaman aşımı yoktur.** Aylık arşivler kendiliğinden silinmez. İkinci diske taşıma aracı hedefteki kopyanın SHA-256 özetini, gzip bütünlüğünü ve SQLite veritabanını doğrular. [Eski uygulamayı durdurma, verileri koruyarak kurma ve diskte yer açma](deploy/depolama.md)

## Hetzner’de Docker ile temiz kurulum

Varsayılan çevirmen TranslateGemma 4B Q4_K_M, 40 DBA cümlesinin 38'inde teknik ve dil denetimlerini geçti. Önceki Riva modeli aynı denetimlerin 28'ini geçti. [Örnek çeviriler ve 4B modellerin bellek ayarları](release/translation-report.md)

Linux ARM64 veya x86-64, Docker Engine ve Compose v2 gerekir. Kurucu sunucudaki Bash, Python 3.9+, OpenSSL 3, curl ve tar araçlarını kullanır. Model sunucunun işlemcisiyle çalışır. Ağırlıkları bellek eşleme ile açar ve bir seferde bir metin çevirir. Model ve SQLite yeni sürümlerde de aynı sunucu klasörlerinde kalır.

**Hetzner sunucusuna doğrudan indirmek için** root terminalinde şu komutu çalıştırın. Kurucu v1.1.3 paketini doğrular, uygun yerel model varsa onu kullanır ve gerekirse modeli sunucuya indirir. İlk kurulumda panel yöneticisi için parola ister. Eski systemd paneli varsa hizmetlerini durdurur. Eski haber arşivi `/var/lib/postgres-gundem` altında kalır. Yeni Docker kurulumunun veri dizini `/srv/postgres-gundem/data` olur.

```bash
curl -fL --retry 3 https://github.com/EnezMutluoglu/postgres-gundem/releases/download/v1.1.3/hetzner-kur.sh -o /root/postgres-gundem-kur.sh && bash /root/postgres-gundem-kur.sh
```

Kurucu aynı Docker sunucusunda çalışan tek bir `cloudflare/cloudflared` bağlayıcısını otomatik seçer ve tünelin ağından paneli sınar. Birden fazla bağlayıcınız veya özel imajınız varsa `CLOUDFLARED_CONTAINER=konteyner-adı bash /root/postgres-gundem-kur.sh` kullanın. Mevcut Cloudflare rotasında **Type** değerini `HTTP`, **URL** değerini `postgres-gundem:8080` yapın. Bağlayıcı Compose ile yeniden oluşturuluyorsa aşağıdaki [Cloudflare Tunnel](#cloudflare-tunnel) ağ ayarını da uygulayın.

Root olarak aşağıdaki komutları çalıştırın. Adımlar dış basın arşivini içeren v1.1.3 sürümüne sabitlenmiştir. İndirdiğiniz kurulum paketinin özetini sürüm sayfasındaki değerle de karşılaştırabilirsiniz. [Kararlı sürüm](https://github.com/EnezMutluoglu/postgres-gundem/releases/tag/v1.1.3)

```bash
set -e
cd /root
mkdir -p postgres-gundem-kurulum
cd postgres-gundem-kurulum
url=https://github.com/EnezMutluoglu/postgres-gundem/releases/download/v1.1.3
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

Çevrimdışı model kurulumu için [v1.0.0 model paketindeki](https://github.com/EnezMutluoglu/postgres-gundem/releases/tag/v1.0.0) `model.gguf.part-00`, `model.gguf.part-01` ve `model-parts.sha256` dosyalarını aynı klasöre aktarın. Bu klasörde `sha256sum -c model-parts.sha256` çalıştırın. Kurulum dizininde `bash get-model.sh /root/model-parcalari` parçaları birleştirip modelin tamamını doğrular. Model Google TranslateGemma'nın GGUF uyarlamasıdır. [Model, dönüştürme bilgisi ve lisans](https://huggingface.co/Menterium/translategemma-4b-it-GGUF/tree/d1709f49e90452b9189e0144cc6826d199616921)

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
| `arsiv/` | Ayın ilk günü 03.15 UTC sonrasında alınan kalıcı sıkıştırılmış arşivler |
| `models/` | Salt okunur yerel model ağırlıkları |
| `manager/` | Etkin ve önceki sürüm, geri dönüş kopyası, kesintiye karşı işlem kaydı |
| `config/` | Yönetici parolasının özeti ve oturum anahtarı |

40 GB disk için en büyük sabit kalem 2,32 GiB'lik modeldir. v1.0.0 ARM64 imaj arşivi 83 MiB, x86-64 imaj arşivi 93 MiB indirir. Konteyner motoru açılmış katmanları ayrıca saklar. Kaynak denetimi aynı haber değişmedikçe yeni kayıt yazmaz. Yeni haberler ve çeviriler canlı SQLite veritabanına eklenir. Her aylık kopya saklanır. Disk doluluğu arttığında eski kopyaları ikinci diske taşıyabilirsiniz. Örnek bir ilk kurulumda veri dizini 268 KiB, arşiv dizini 44 KiB tuttu. Gerçek büyümeyi yukarıdaki `du` komutuyla izleyebilirsiniz. Yerel kurulum paketini de sunucuda tutarsanız modelin ikinci kopyası 2,32 GiB daha kullanır.

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

