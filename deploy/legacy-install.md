# Postgres Gündem

PostgreSQL güvenlik açıklarını, bakım sürümlerini, geliştirme notlarını ve eklentileri tek sayfada Türkçe okuyun. Sunucu başlatıldığında ve ardından her saat verileri yeniler. Açık sekme yeni kayıtları 30 saniye içinde gösterir. **Yenile** düğmesi sunucudaki son bülteni getirir.

## 1. Mimarinize uygun tam paketi gönderin

Debian 12 veya 13 sunucusunda `dpkg --print-architecture` çalıştırın. Her iki paket de 2,76 GB Riva GGUF modelini, Debian 12 tabanında derlenmiş llama.cpp b12532 motorunu, paneli, aylık arşivlemeyi ve Docker tünel köprüsünü içerir. Kurulum için yaklaşık 10 GB boş disk alanı, yerel çeviri için 8 GB RAM önerilir. APT ve Python çalışma zamanı bağımlılıkları internet üzerinden kurulur. Sunucuda derleyici kurulması gerekmez.

| Komut çıktısı | Gönderilecek dosya ve yanındaki `.sha256` |
| --- | --- |
| `arm64` | `postgres-gundem-debian12-13-arm64.tar` |
| `amd64` (Intel/AMD x86-64) | `postgres-gundem-debian12-13-amd64.tar` |

x86-64 kurucusu işlemcinin komut setini denetler. Uyumlu işlemcilerde AVX2 için derlenmiş motoru, diğerlerinde temel x86-64 motorunu kurar.

Windows'ta iki tam paketin bulunduğu klasörde PowerShell açın. Aşağıdaki örnekte ARM için `arm64`, Intel/AMD için `amd64` kullanın. `root@sunucu` yerine kendi SSH adresinizi yazın.

```powershell
$mimari = "arm64"
$paket = "postgres-gundem-debian12-13-$mimari.tar"
scp $paket "$paket.sha256" root@sunucu:/root/
ssh root@sunucu
```

## 2. Paketi doğrulayın ve kurun

Debian'da root olarak çalıştırın. Betik kurulu modelin SHA-256 özetini kontrol eder ve aynı model varsa onu kullanır. Yükseltmede SQLite haber ve çeviri verileri aynı dizinde tutulur.

```bash
(
  set -eu
  cd /root
  paket="postgres-gundem-debian12-13-$(dpkg --print-architecture).tar"
  sha256sum -c "$paket.sha256"
  calisma=$(mktemp -d /root/postgres-gundem.XXXXXXXX)
  trap 'rm -rf -- "$calisma"' EXIT
  tar -xf "$paket" -C "$calisma"
  TMPDIR="$calisma" bash "$calisma/postgres-gundem/install.sh" --paketten
)
```

Panel ve model açılışta otomatik başlar. Kurucu iki HTTP yanıtını denetler ve aylık arşiv zamanlayıcısını etkinleştirir. Geçici açma dizini temizlenir. Arşivin bilgisayarınızda kopyası varsa başarılı kurulumdan sonra `/root` altındaki yükleme dosyalarını silerek yaklaşık 2,76 GB geri kazanabilirsiniz.

## 3. Alan adını bağlamadan önce paneli kontrol edin

```sh
systemctl is-active postgres-gundem postgres-gundem-model
curl -fsS -o /dev/null -w 'Panel HTTP %{http_code}\n' http://127.0.0.1:8080/
curl -fsS --retry 30 --retry-all-errors --retry-delay 2 http://127.0.0.1:18081/health
```

Sırasıyla iki `active` satırı, `Panel HTTP 200` ve modelden `{"status":"ok"}` beklenir. İlk yüklemede model hazır olana kadar sağlık denetimi kısa süreliğine 503 döndürebilir. Panel, haberleri ve Türkçe çevirileri geldikçe gösterir.

## 4. Cloudflare tünelini Debian'a bağlayın

1. Cloudflare hesabınızda alan adınızın **Active** olduğunu kontrol edin. Henüz eklemediyseniz önce alan adını ekleyip Cloudflare'ın gösterdiği DNS kurulumunu tamamlayın. Aşağıdaki örnekte panel adresi `postgres.example.com`. `example.com` yerine kendi alan adınızı kullanın. [Alan adını etkinleştirme](https://developers.cloudflare.com/dns/zone-setups/full-setup/setup/)
2. Cloudflare panosunda **Networking → Tunnels** sayfasını açın. **Bu Debian makinesinde zaten çalışan ve panodan yönetilen bir tüneliniz varsa** onu seçip doğrudan 5. bölüme geçin. Aynı sunucuda çalışan tünel, birden fazla alan adına hizmet verebilir. [Tünel kurulumu](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/)
3. Yeni tünel için **Create a tunnel** seçeneğine tıklayın. Adını `postgres-gundem` girip oluşturun. İşletim sistemi olarak **Debian** seçin. Mimari sorulursa sunucuda `dpkg --print-architecture` çalıştırın. `amd64` için x86-64, `arm64` için ARM64 seçin.
4. Cloudflare'ın **Install and run a connector** ekranında verdiği Debian kurulum ve servis komutlarını **panelin kurulu olduğu sunucuda** çalıştırın. Servis komutundaki token bu tünele özeldir. Panodaki gerçek komutu kullanın ve token'ı özel tutun. Cloudflare bağlantıyı gördüğünde **Continue** seçeneğine tıklayın.

   ```sh
   systemctl is-active cloudflared
   ```

   Çıktı `active` olmalı. `cloudflared` paketini ayrıca kurmanız gerekirse Cloudflare'ın Debian için sunduğu kararlı APT deposunu kullanın. [Resmî Debian paketi](https://pkg.cloudflare.com/)

## 5. Alan adını panele yönlendirin

Debian sunucusunda root olarak `bash /opt/postgres-gundem/tunel-koprusu.sh` çalıştırın. Sunucudaki `cloudflared` aynı ağ alanındaysa hedef `http://127.0.0.1:8080` olur. Docker köprü ağı kullanılıyorsa betik ağ geçidini bulur, yalnızca o köprü adresinde 18080 portunu dinleyen bir systemd soketi kurar ve tünelin ağından HTTP 200 aldığını doğrular. Örneğin geçit `172.17.0.1` ise çıktı `http://172.17.0.1:18080` olur. Kendi sunucunuzda betiğin yazdığı değeri kullanın. Birden fazla bağlayıcı varsa betiğe panel tünelinin `cloudflared` PID değerini verin.

Tünelinizde **Routes → Add route → Published application** yolunu açın ve şu alanları doldurun. [Cloudflare yayın adımları](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/)

| Alan | Değer |
| --- | --- |
| Subdomain | `postgres` |
| Domain | Kendi alan adınız |
| Path | Boş bırakın |
| Service URL | Betiğin yazdığı `Service URL` değeri |

Arayüz protokol ve adresi ayrı sorarsa **Type** için `HTTP`, **URL** için betiğin verdiği IP ve portu girin. Mevcut alan adında ilgili rotayı düzenleyin. Yeni alan adında **Add route** ile kaydedin. Yayın rotası alan adını internete açar. Yalnızca belirli kullanıcılar erişecekse aynı alan adını Cloudflare Access uygulaması ve izin kuralıyla koruyun. Çeviri motoru `127.0.0.1:18081` üzerinde çalışır.

Cloudflare DNS sayfasında seçtiğiniz alt alan adının tünele yönlendiğini kontrol edin. Tünel DNS hedefi `<TÜNEL-KİMLİĞİ>.cfargotunnel.com` biçimindedir. Aynı ad üzerinde başka bir web sitesi varsa panel için kullanılmayan bir alt alan adı seçebilirsiniz. Tünel sunucudan dışarı bağlantı kurduğu için modemde port yönlendirme veya sunucunun genel IP adresine bir A kaydı gerekmez. [Tünel DNS kayıtları](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/routing-to-tunnel/dns/)

## 6. Dışarıdan doğrulayın

Telefonunuzda mobil veriyle `https://postgres.example.com` adresinin kendi alan adınıza uyarlanmış hâlini açın. **Günlük bülten** başlığını ve ilk tarama tamamlandığında haberleri görmelisiniz. Komut satırından da aynı adresi test edebilirsiniz.

```sh
curl -sS -o /dev/null -w 'Domain HTTP %{http_code}\n' https://postgres.example.com/
```

| Belirti | Kontrol |
| --- | --- |
| Tünel **Down** veya hata **1033** | Debian'da `systemctl is-active cloudflared` ve `sudo journalctl -u cloudflared -n 40 --no-pager` ile bağlantıyı kontrol edin. Çıkış trafiği kısıtlı ağlarda Cloudflare'ın 7844 bağlantı noktasına erişim gerekir. |
| Domain **502** döndürüyor | Önce panelin HTTP 200 verdiğini kontrol edin. Ardından köprü betiğini çalıştırıp Cloudflare rotasındaki protokol, IP ve portu betiğin çıktısıyla karşılaştırın. |
| Domain bulunamıyor | Cloudflare'da alan adının etkin olduğunu, alt alan adının yazımını ve tünel DNS kaydını kontrol edin. |

[Cloudflare Tunnel sorun giderme](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/troubleshoot-tunnels/common-errors/)

## İşletim

Haberler ve Türkçe çeviriler SQLite'ta tutulur. Ölçülen bir kurulumda 273 haber ve 391 çevrilmiş metin 528 KiB, aynı veritabanının gzip kopyası 111 KiB tuttu. Güncel boyut ve zamanlama için root olarak çalıştırın.

```bash
du -sh /opt/postgres-gundem
du -ch /var/lib/postgres-gundem/gundem.sqlite*
systemctl list-timers --all postgres-gundem-arsiv.timer
ls -lh /var/lib/postgres-gundem/arsiv/
```

Her ayın 1'inde 03.15 UTC'de (Türkiye saatiyle 06.15) SQLite'ın çevrimiçi yedekleme API'siyle tutarlı bir kopya alınır, doğrulanır ve sıkıştırılır. v1.1.0 ile tüm aylık dosyalar süresiz tutulur. Haber geçmişi panelden okunabilir. İlk tarama henüz kayıt getirmediyse haberler geldikten sonra `systemctl start postgres-gundem-arsiv.service` ile ilk kopyayı alabilirsiniz. Zamanlamayı kapatmak için `systemctl disable --now postgres-gundem-arsiv.timer` çalıştırın.

```sh
systemctl status postgres-gundem postgres-gundem-model
journalctl -u postgres-gundem -u postgres-gundem-model -f
```

SQLite haberleri, çevirileri ve kaynakların son başarılı kontrol zamanlarını `/var/lib/postgres-gundem` altında tutar. Kaynağa erişilemediğinde son kayıtlar korunur. Okundu bilgisi her ziyaretçinin tarayıcısında saklanır. Ziyaretçiler sunucudaki taramayı veya çeviriyi tetikleyemez. Yeni uygulama sürümünü yüklemek için aynı kurulum komutunu çalıştırabilirsiniz.

Panel, çevirilerde PostgreSQL terimleri için bir sözlük kullanır. Örneğin `maintenance update` için **bakım güncellemesi**, `primary server` için **birincil sunucu**, `standby server` için **bekleme sunucusu** kullanılır. Güncellemeden sonraki ilk açılışta, önbellekte bu terimlerle uyuşmayan çeviriler yeniden çevrilmek üzere sıraya alınır. Bu sırada haberde özgün İngilizce metni açabilirsiniz.

Yama talimatlarında modelin eklediği gerekçe ifadeleri İngilizce kaynak cümleyle karşılaştırılır. Örneğin yalnızca yedek almayı söyleyen bir talimata eklenen “güvenlik amaçlı” ifadesi ayıklanır. Kaynak güvenlik gerekçesini açıkça belirtiyorsa çeviride korunur. Denetimden geçmeyen çeviriler yeniden denenir ve bu sırada özgün metin okunabilir. Bu denetim daha önce kaydedilmiş model çevirilerine de uygulanır.

**Kaynaklar.** Sürüm eşleşmeleri PostgreSQL'in CVE kayıtlarından, güncel bakım sürümü ve destek tarihleri sürüm dizininden gelir. CommitFest durumları inceleme aşamasını, PGXN kayıtları topluluk paketlerini gösterir. Teknik doğrulama için her kartta kaynak bağlantısı bulunur. [Güvenlik kayıtları](https://www.postgresql.org/support/security/) · [Sürüm dizini](https://www.postgresql.org/versions.json) · [CommitFest](https://commitfest.postgresql.org/) · [PGXN](https://pgxn.org/recent/)

**Model ve görseller.** Çeviri sunucuda Riva Translate 4B v2 ile yapılır. Model dosyası ve llama.cpp paketi sürüme sabitlenmiş SHA-256 özetiyle doğrulanır. Fil logosu PostgreSQL projesine aittir. Yazı tipi lisansları `static/fonts` dizinindedir. [NVIDIA model kartı](https://huggingface.co/nvidia/Riva-Translate-4B-Instruct-v2) · [Q4_K_M dosyası](https://huggingface.co/liodon-ai/Riva-Translate-4B-Instruct-v2-imatrix-GGUF) · [PostgreSQL görsel kaynakları](https://www.postgresql.org/about/press/)

Yavaş işlemcilerde arka plandaki her çeviri isteği için systemd hizmeti en fazla 20 dakika bekler. Bu sırada paneldeki haberler okunabilir. Bu süreyi değiştirmek için `systemctl edit postgres-gundem` ile hizmetin `[Service]` bölümüne `Environment=GUNDEM_MODEL_TIMEOUT=1200` ekleyip saniye değerini değiştirin ve hizmeti yeniden başlatın.

## Test

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```

## Dağıtım paketlerini yeniden üretme

Debian 12 x86-64 derleme makinesinde `cmake`, `ninja-build`, `g++`, `g++-aarch64-linux-gnu` ve Python 3.11 gerekir. `kaynak.tar.gz` olarak llama.cpp b12532 etiketinin kaynak arşivini, `.runtime/` altında modelin doğrulanmış GGUF dosyasını kullanın. Betik kaynak özetini kontrol eder. Paketleyici ELF mimarisini, model özetini ve arşivdeki dosyaları doğrular. [Sabitlenmiş llama.cpp kaynağı](https://codeload.github.com/ggml-org/llama.cpp/tar.gz/refs/tags/b12532)

```bash
for mimari in arm64 amd64; do
  bash release/build-engine.sh "$mimari" kaynak.tar.gz .runtime || break
  python3 release/package.py "$mimari" \
    --engine ".runtime/llama-b12532-bin-debian12-$mimari.tar.gz" --output paket || break
done
```
