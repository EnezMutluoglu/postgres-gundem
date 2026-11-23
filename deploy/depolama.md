# Hetzner’de uygulamayı yenileme ve haber arşivini taşıma

## Önce kurulum türünü belirleyin

Root oturumunda aşağıdaki iki komutun çıktısını kontrol edin.

```bash
docker ps -a --format '{{.Names}}  {{.Status}}' --filter name=postgres-gundem
systemctl show postgres-gundem.service -p FragmentPath -p ActiveState
```

### Docker sürümü zaten kuruluysa

Çalışan panelde **Ayarlar → Şimdi denetle → Güncelle** yolunu kullanın. İşlem v1.1.3 imajını mimariye göre indirir, SQLite kopyasını alır ve sağlık kontrolünü çalıştırır. Model bir kez doğrulanır. Veri ve arşivler aynı klasörlerde kalır. Dış basın sekmesi ilk tarama sürerken açılabilir.

### Eski systemd kurulumu varsa

1. [v1.1.3 kurulum arşivini](https://github.com/EnezMutluoglu/postgres-gundem/releases/tag/v1.1.3) indirin. Mevcut SQLite dosyasını, arşivleri ve eski model hizmetini geçiş betiği tanır.
2. Aşağıdaki komutları root olarak çalıştırın. Son satır, daha önce gönderdiğiniz model dahil paketin açılmış olduğu yolu kullanır. Model parçalarını gönderdiyseniz bunun yerine parça klasörünün tam yolunu girin.
3. Betik eski paneli ve model hizmetini durdurur. Yeni dizine tutarlı SQLite kopyası alır ve bütün aylık arşivleri aktarır. Yeni servislerin sağlığını doğruladıktan sonra eski servislerin otomatik başlangıcını kapatır.

```bash
(
  set -eu
  mkdir -p /root/postgres-gundem-v1.1.3
  cd /root/postgres-gundem-v1.1.3
  url=https://github.com/EnezMutluoglu/postgres-gundem/releases/download/v1.1.3
  curl -fLO "$url/kurulum.tar.gz"
  curl -fLO "$url/kurulum.tar.gz.sha256"
  sha256sum -c kurulum.tar.gz.sha256
  tar -xzf kurulum.tar.gz
  bash container/hetzner-gecis.sh /root/docker-v1.0.0/translategemma-4b-it-Q4_K_M.gguf
)
```

Eski sistemdeki haberler `/var/lib/postgres-gundem`, Docker’daki veritabanı `/srv/postgres-gundem/data`, yeni arşivler `/srv/postgres-gundem/arsiv` altındadır. Cloudflare bağlayıcısı `postgres-gundem-origin` ağına bağlı olmalı ve rota `http://postgres-gundem:8080` adresini göstermelidir.

**Eski uygulama dosyalarını kaldırmak için** kurulum arşivini açtığınız dizinden şu betiği root olarak çalıştırın. Temizlik isteğe bağlıdır. Docker kurulumundan önce çalıştırırsanız yeni panel açılana kadar kesinti olur. Betik eski systemd dizinini, ayrı veritabanının SQLite bütünlüğünü ve haber sayısını denetler. Silinecek dizini gösterir ve `KALDIR` yazmanızı ister. Onayladığınızda eski hizmetleri durdurur ve `/opt/postgres-gundem` dizinini kaldırır. Daha önce göndermiş olduğunuz model paketini `/root` altında tutun.

```bash
bash container/eski-uygulamayi-kaldir.sh
```

Yalnızca çalışan Docker panelini geçici durdurup açmak için `docker stop postgres-gundem-updater postgres-gundem-web-1 postgres-gundem-model-1` ve ardından `docker start postgres-gundem-model-1 postgres-gundem-web-1 postgres-gundem-updater` kullanın.

## Aylık arşivleri ikinci diske taşıma

Her dosya kendi başına okunabilir tam SQLite kopyasıdır. Haftalık dış kaynak kayıtları, özgün akış metinleri, çeviriler ve önceki sürümler bu veritabanındadır. Uygulama doluluk veya yaş nedeniyle haber ya da aylık kopya silmez. Daha eski sürümlerin zamanında döndürdüğü arşivleri geri getirmek için elinizdeki bağımsız yedek gerekir.

Aşağıda ikinci diskin bağlama noktası `/mnt/haber-diski` kabul edilmiştir. Kendi bağlama noktanızla değiştirin. Betik v1.1.3 kurulum paketinde yer alır. Sadece web’den güncelleme yaptıysanız yukarıdaki kurulum arşivini indirip açmanız yeterlidir.

```bash
(
  set -eu
  mountpoint -q /mnt/haber-diski
  install -d -m 700 /mnt/haber-diski/postgres-gundem-arsiv
  cd /root/postgres-gundem-v1.1.3/container
  python3 arsiv-tasi.py /mnt/haber-diski/postgres-gundem-arsiv
)
```

İlk komut doğrulanmış kopyayı oluşturur. Hedef diskteki kopyayı esas alıp yerel alanda yer açmaya hazır olduğunuzda:

```bash
python3 /root/postgres-gundem-v1.1.3/container/arsiv-tasi.py /mnt/haber-diski/postgres-gundem-arsiv --tasi
```

Araç her dosyada SHA-256, gzip bütünlüğü ve SQLite `quick_check` denetimlerini yapar. Aynı adla farklı bir hedef dosya görürse durur. Doğrulamadan sonra yerel sıkıştırılmış kopyayı kaldırır ve yerine hedef yol ile özeti içeren küçük bir teslim kaydı bırakır. Hedefte geçici olarak açılmış veritabanı kadar ek boş alan gerekir. Canlı bülten SQLite'tan okunmaya devam eder. İkinci diskte tek kopya bırakacaksanız diskin kaybına karşı ayrıca yedek bulundurun.

## Canlı veritabanı da yer kaplarsa

Docker kurulumunda tüm `/srv/postgres-gundem` dizinini ikinci diske taşıyıp aynı yola bağlayabilirsiniz. Bu, model, canlı SQLite, arşivler ve yönetici ayarlarını birlikte taşır. Yalnız bu proje için ayrılmış hedefi kullanın. Şu komutlar disk bağlama düzenini değiştirmeden önce kopyayı doğrular.

```bash
(
  set -eu
  mountpoint -q /mnt/haber-diski
  hedef=/mnt/haber-diski/postgres-gundem-canli
  test ! -e "$hedef"
  mkdir -m 700 "$hedef"
  docker stop postgres-gundem-updater postgres-gundem-web-1 postgres-gundem-model-1
  trap 'docker start postgres-gundem-model-1 postgres-gundem-web-1 postgres-gundem-updater >/dev/null' EXIT
  rsync -aHAX --numeric-ids /srv/postgres-gundem/ "$hedef/"
  test -z "$(rsync -aHAXnci --numeric-ids /srv/postgres-gundem/ "$hedef/")"
  python3 - "$hedef/data/gundem.sqlite" <<'PY'
from pathlib import Path
import sqlite3, sys
con = sqlite3.connect(Path(sys.argv[1]).as_uri()+"?mode=ro", uri=True)
assert con.execute("PRAGMA quick_check").fetchall() == [("ok",)]
PY
  test ! -e /srv/postgres-gundem-tasima-oncesi
  mv -T /srv/postgres-gundem /srv/postgres-gundem-tasima-oncesi
  mkdir /srv/postgres-gundem
  if ! mount --bind "$hedef" /srv/postgres-gundem; then
    rmdir /srv/postgres-gundem
    mv -T /srv/postgres-gundem-tasima-oncesi /srv/postgres-gundem
    exit 1
  fi
)
```

Yeniden başlatmadan önce ikinci diskin kendi UUID'siyle kalıcı olarak bağlandığını doğrulayın. Bind mount için `/etc/fstab` içinde tek kayıt kullanın:

```
/mnt/haber-diski/postgres-gundem-canli /srv/postgres-gundem none bind,x-systemd.requires-mounts-for=/mnt/haber-diski 0 0
```

`systemctl daemon-reload`, `findmnt --verify` ve `findmnt --mountpoint /srv/postgres-gundem` ile doğrulayın. Paneli ve tarihli kayıtları kontrol edin. `/srv/postgres-gundem-tasima-oncesi` eski diskteki tam kopyadır. Bu kopyayı başka doğrulanmış depolamaya aldıktan sonra eski diskteki alanı serbest bırakabilirsiniz.
