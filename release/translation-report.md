# Yerel model seçimi

Varsayılan model **TranslateGemma 4B IT, Q4_K_M**. Üç model aynı 40 PostgreSQL cümlesini çevirdi. Aynı son kontrol kümesini kaydedilen bütün çıktılara uyguladık. Denetim sürüm ve teknik tanımlayıcıları, yama talimatının yönünü, olumsuzluğu, gerekçeyi ve her örnekte beklenen sözcükleri kapsıyor. Bir çeviri teknik denetimle durdurulduğunda sonuç dosyasında hata metni bulunuyor. [40 kaynak cümle ve ölçütleri](../tests/translation-cases.json) · [Her modelin verdiği karşılık](translation-results.json)

| Model | Kontrolden geçen örnek | DBA açısından fark |
| --- | ---: | --- |
| TranslateGemma 4B Q4_K_M | 38 / 40 | Eksik indeksi, geçici tablonun commit sırasında silinmesini ve kurtarma sırasında VACUUM çalıştırılmamasını aktardı. |
| Riva Translate 4B v2 Q4_K_M | 28 / 40 | “Missing index” için “yanlış bir indeks”, yükseltme için “yükleme” dedi. |
| OPUS-MT en-tr INT8 | 32 / 40 | “From 15.7 onward” için 15.7'yi dışlayan “15.7'den sonraki” ifadesini kullandı. Commit sözcüğünü “taahhüt” olarak çevirdi. |

TranslateGemma, “Take a full backup before applying the maintenance update.” cümlesini **“Bakım güncellemesini uygulamadan önce tam bir yedek alın.”** diye çevirdi. Kaynakta “For security reasons” yer aldığında gerekçeyi de çevirdi. Testte en yüksek puanı alan modelin de üslup kusurları var. Örneğin WAL kayıtlarının yazılmasını “yeni WAL kayıtlarını kaydeder” diye aktardı. Bir başka örnekte “için” bekleyen sözcük kontrolü, “böylece” ile kurulan amaç cümlesini reddetti. Puanlar bu 40 örneğe aittir. Etkilenen ve düzeltilen sürümler doğrudan PostgreSQL’in kayıtlarından alınır.

İki 4B modeli WSL Debian üzerinde yalnız CPU ile, ikişer çekirdek, 2.880 MiB bellek sınırı, kapalı swap, aynı llama.cpp sürümü ve aynı bağlamla çalıştırdık. Cümle başına ortanca süre TranslateGemma için 15,88 saniye, Riva için 10,61 saniyeydi. Bunlar paylaşımlı test makinesindeki sürelerdir. OPUS ayrı bir INT8 çeviri motoruyla sınandı. GGUF ağırlıkları bellek eşlemeyle açılır. Linux gereken dosya sayfalarını belleğe alıp baskı altında serbest bırakabilir. Model dosyası 2.489.909.312 bayt (2,32 GiB). Dosya önbelleğinin kime yazıldığı ölçümü etkilediğinden konteynerin anlık kullanımı toplam sunucu RAM gereksinimini göstermez.

Ayrıca yayımlanan v1.0.0 imajını 2 vCPU ve 4 GiB RAM ayrılmış bir AlmaLinux 9.9 sanal makinesinde sınadık. SELinux enforcing modundayken Podman sistem servisi aynı yama cümlesini çevirdi. systemd model hizmeti için 2.795.339.776 bayt (2,60 GiB) tepe kullanım ölçtü. Bu ölçüme panel, işletim sistemi ve sunucudaki diğer hizmetler dahil değildir.

Saatlik haber taraması çeviri kuyruğundan bağımsızdır. Model bir defada bir metin işler. Kaynakta olmayan gerekçe, bozuk sürüm bilgisi veya sözlük uyuşmazlığı yakalanırsa İngilizce kaynak kullanılabilir ve çeviri tekrar denenir. CPU ve bellek testini çalıştırmak için `bash release/test-image.sh YEREL_IMAJ` komutunu kullanabilirsiniz. 40 cümlelik karşılaştırmanın giriş noktası `release/benchmark.py` dosyasıdır.

Model kartları ve dönüşüm bilgileri [Google TranslateGemma](https://huggingface.co/google/translategemma-4b-it), [kullanılan GGUF dosyası](https://huggingface.co/Menterium/translategemma-4b-it-GGUF/tree/d1709f49e90452b9189e0144cc6826d199616921), [NVIDIA Riva](https://huggingface.co/nvidia/Riva-Translate-4B-Instruct-v2) ve [Helsinki-NLP OPUS](https://huggingface.co/Helsinki-NLP/opus-mt-tc-big-en-tr) sayfalarındadır.
