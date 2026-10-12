"""One-page samples in every source language the app offers (German and Chinese have their own, larger set).

Each is the same acceptance report — running header, title, date line, headings, a paragraph, a defects
table, a labelled diagram with its caption, a conclusion and a page footer — so one English reference
(samples/reference/acceptance-report.en.md) fits them all. Each comes as a PDF with a text layer and as an
image-only scan. Scripts whose shaped text PyMuPDF can't map back to Unicode (Arabic, Devanagari, Bengali)
get the scan only: a sample with a garbled text layer would test the wrong thing.

What it exercises: the vision OCR on the script (headers, footers, tables, text inside a picture, captions),
the OCR check, the analysis questions (each conclusion has a legal term — "réception avec
réserves", "collaudo con riserva", 条件付き受入 — and the UPS abbreviation is local: SAI, ASI, ИБП, KGK…),
and translation into English.

    uv run python scripts/make_language_samples.py        # writes samples/languages/
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_samples import ROOT, Block, flow_pdf, norm, pdf_bytes, scanned  # noqa: E402

OUT = ROOT / "samples" / "languages"


@dataclass
class Lang:
    code: str
    name: str
    header: str
    title: str
    meta: str
    h1: str
    p1: str
    h2: str
    table: list[list[str]]
    labels: tuple[str, str, str]  # distribution board, UPS, cable tray
    note: str  # earth connection missing
    caption: str
    h3: str
    p2: str
    footer: str
    rtl: bool = False
    terms: list[str] = field(default_factory=list)  # what the analysis is likely to ask about (for TESTING.md)


LANGS = [
    Lang("es", "Spanish", "Subestación Norte · Proyecto UW-2291 · Confidencial",
         "Acta de recepción – Subestación Norte", "Fecha: 14/03/2026 | N.º de proyecto: UW-2291",
         "1. Alcance de la recepción",
         "La recepción abarca la renovación de la aparamenta de 110 kV, incluidos los sistemas secundarios. Los trabajos "
         "se ejecutaron conforme a la partida 4.2.7 del presupuesto. El contratista ha entregado todos los informes de ensayo.",
         "2. Defectos detectados",
         [["N.º", "Descripción", "Plazo"], ["1", "Bandeja de cables del sótano sin puesta a tierra", "30/04/2026"],
          ["2", "Rotulación de las salidas incompleta", "15/04/2026"],
          ["3", "Trabajos pendientes en el circuito intermedio del SAI", "30/04/2026"]],
         ("Cuadro de distribución", "SAI", "Bandeja de cables"), "Falta la conexión a tierra",
         "Fig. 1: Vista general del sótano", "3. Conclusión",
         "La instalación se recibe con reservas hasta la subsanación de los defectos indicados. La reinspección está "
         "prevista para la semana 18. Hasta entonces se retiene el 5 % del importe del contrato como garantía.",
         "Página {page} de {pages}", terms=["recepción con reservas", "SAI"]),
    Lang("fr", "French", "Poste Nord · Projet UW-2291 · Confidentiel",
         "Procès-verbal de réception – Poste Nord", "Date : 14/03/2026 | N° de projet : UW-2291",
         "1. Objet de la réception",
         "La réception porte sur le renouvellement de l'appareillage 110 kV, y compris le contrôle-commande. Les travaux "
         "ont été exécutés conformément au poste 4.2.7 du bordereau des prix. L'entreprise a remis l'ensemble des "
         "procès-verbaux d'essais.",
         "2. Défauts constatés",
         [["N°", "Description", "Délai"], ["1", "Chemin de câbles du sous-sol non relié à la terre", "30/04/2026"],
          ["2", "Repérage des départs incomplet", "15/04/2026"],
          ["3", "Travaux restants sur le circuit intermédiaire de l'ASI", "30/04/2026"]],
         ("Tableau de distribution", "ASI", "Chemin de câbles"), "Mise à la terre manquante",
         "Fig. 1 : Vue d'ensemble du sous-sol", "3. Conclusion",
         "L'installation est réceptionnée avec réserves jusqu'à la levée des défauts ci-dessus. La visite de levée des "
         "réserves est prévue en semaine 18. D'ici là, une retenue de garantie de 5 % du montant du marché est appliquée.",
         "Page {page} sur {pages}", terms=["réceptionnée avec réserves", "ASI", "contrôle-commande"]),
    Lang("it", "Italian", "Sottostazione Nord · Progetto UW-2291 · Riservato",
         "Verbale di collaudo – Sottostazione Nord", "Data: 14/03/2026 | N. progetto: UW-2291",
         "1. Oggetto del collaudo",
         "Il collaudo riguarda il rinnovo delle apparecchiature di manovra a 110 kV, compresi i sistemi secondari. I lavori "
         "sono stati eseguiti secondo la voce 4.2.7 del computo metrico. L'appaltatore ha consegnato tutti i rapporti di prova.",
         "2. Difetti riscontrati",
         [["N.", "Descrizione", "Scadenza"], ["1", "Passerella portacavi nel seminterrato non collegata a terra", "30/04/2026"],
          ["2", "Siglatura delle partenze incompleta", "15/04/2026"],
          ["3", "Lavori residui sul circuito intermedio dell'UPS", "30/04/2026"]],
         ("Quadro di distribuzione", "UPS", "Passerella portacavi"), "Collegamento a terra mancante",
         "Fig. 1: Panoramica del seminterrato", "3. Conclusione",
         "L'impianto è collaudato con riserva fino all'eliminazione dei difetti sopra elencati. Il nuovo sopralluogo è "
         "previsto nella settimana 18. Fino ad allora viene trattenuto il 5% dell'importo contrattuale a titolo di garanzia.",
         "Pagina {page} di {pages}", terms=["collaudato con riserva", "computo metrico"]),
    Lang("pt", "Portuguese", "Subestação Norte · Projeto UW-2291 · Confidencial",
         "Termo de recebimento – Subestação Norte", "Data: 14/03/2026 | Nº do projeto: UW-2291",
         "1. Objeto do recebimento",
         "O recebimento abrange a renovação dos equipamentos de manobra de 110 kV, incluindo os sistemas secundários. Os "
         "serviços foram executados conforme o item 4.2.7 da planilha orçamentária. A contratada entregou todos os "
         "relatórios de ensaio.",
         "2. Defeitos constatados",
         [["Nº", "Descrição", "Prazo"], ["1", "Eletrocalha do subsolo sem aterramento", "30/04/2026"],
          ["2", "Identificação das saídas incompleta", "15/04/2026"],
          ["3", "Serviços pendentes no circuito intermediário do nobreak", "30/04/2026"]],
         ("Quadro de distribuição", "Nobreak", "Eletrocalha"), "Falta o aterramento",
         "Fig. 1: Visão geral do subsolo", "3. Conclusão",
         "A instalação é recebida provisoriamente, com ressalvas, até a correção dos defeitos acima. A nova vistoria está "
         "prevista para a semana 18. Até lá, fica retido 5% do valor do contrato como caução.",
         "Página {page} de {pages}", terms=["recebida provisoriamente, com ressalvas", "nobreak", "caução"]),
    Lang("nl", "Dutch", "Onderstation Noord · Project UW-2291 · Vertrouwelijk",
         "Proces-verbaal van oplevering – Onderstation Noord", "Datum: 14-03-2026 | Projectnr.: UW-2291",
         "1. Omvang van de oplevering",
         "De oplevering betreft de vernieuwing van de 110 kV-schakelinstallatie, inclusief de secundaire systemen. De "
         "werkzaamheden zijn uitgevoerd volgens post 4.2.7 van het bestek. De opdrachtnemer heeft alle testrapporten overgedragen.",
         "2. Geconstateerde gebreken",
         [["Nr.", "Omschrijving", "Termijn"], ["1", "Kabelgoot in de kelder niet geaard", "30-04-2026"],
          ["2", "Codering van de uitgaande velden onvolledig", "15-04-2026"],
          ["3", "Restwerkzaamheden aan de tussenkring van de UPS", "30-04-2026"]],
         ("Verdeelkast", "UPS", "Kabelgoot"), "Aardverbinding ontbreekt",
         "Afb. 1: Overzicht kelder", "3. Conclusie",
         "De installatie wordt onder voorbehoud opgeleverd tot de bovengenoemde gebreken zijn hersteld. De herkeuring is "
         "gepland in week 18. Tot die tijd wordt 5% van de aanneemsom ingehouden als zekerheid.",
         "Pagina {page} van {pages}", terms=["onder voorbehoud opgeleverd", "bestek"]),
    Lang("pl", "Polish", "Stacja Północ · Projekt UW-2291 · Poufne",
         "Protokół odbioru – Stacja Północ", "Data: 14.03.2026 | Nr projektu: UW-2291",
         "1. Przedmiot odbioru",
         "Odbiór obejmuje modernizację rozdzielnicy 110 kV wraz z obwodami wtórnymi. Prace wykonano zgodnie z pozycją "
         "4.2.7 przedmiaru robót. Wykonawca przekazał wszystkie protokoły z badań.",
         "2. Stwierdzone usterki",
         [["Lp.", "Opis", "Termin"], ["1", "Korytko kablowe w piwnicy nieuziemione", "30.04.2026"],
          ["2", "Niekompletne oznakowanie pól odpływowych", "15.04.2026"],
          ["3", "Prace pozostałe w obwodzie pośrednim UPS", "30.04.2026"]],
         ("Rozdzielnica", "UPS", "Korytko kablowe"), "Brak uziemienia",
         "Rys. 1: Widok ogólny piwnicy", "3. Wnioski",
         "Instalację odebrano warunkowo do czasu usunięcia wymienionych usterek. Ponowny odbiór zaplanowano na 18. "
         "tydzień. Do tego czasu zatrzymuje się 5% wynagrodzenia umownego jako zabezpieczenie.",
         "Strona {page} z {pages}", terms=["odebrano warunkowo", "przedmiar robót"]),
    Lang("sv", "Swedish", "Ställverk Norr · Projekt UW-2291 · Konfidentiellt",
         "Besiktningsprotokoll – Ställverk Norr", "Datum: 2026-03-14 | Projektnr: UW-2291",
         "1. Besiktningens omfattning",
         "Besiktningen omfattar förnyelsen av 110 kV-ställverket inklusive sekundärsystemen. Arbetena har utförts enligt "
         "post 4.2.7 i mängdförteckningen. Entreprenören har överlämnat samtliga provningsprotokoll.",
         "2. Konstaterade fel",
         [["Nr", "Beskrivning", "Frist"], ["1", "Kabelstege i källaren ej jordad", "2026-04-30"],
          ["2", "Märkning av utgående fack ofullständig", "2026-04-15"],
          ["3", "Återstående arbeten på UPS-enhetens mellanled", "2026-04-30"]],
         ("Fördelningscentral", "UPS", "Kabelstege"), "Jordanslutning saknas",
         "Fig. 1: Översikt källare", "3. Slutsats",
         "Anläggningen godkänns med förbehåll tills ovanstående fel har åtgärdats. Efterbesiktning planeras till vecka 18. "
         "Fram till dess innehålls 5 % av kontraktssumman som säkerhet.",
         "Sida {page} av {pages}", terms=["godkänns med förbehåll", "efterbesiktning"]),
    Lang("tr", "Turkish", "Kuzey Trafo Merkezi · Proje UW-2291 · Gizli",
         "Kabul Tutanağı – Kuzey Trafo Merkezi", "Tarih: 14.03.2026 | Proje No.: UW-2291",
         "1. Kabulün kapsamı",
         "Kabul, ikincil sistemler dahil olmak üzere 110 kV şalt tesisinin yenilenmesini kapsar. İşler, keşif cetvelinin "
         "4.2.7 numaralı kalemine uygun olarak yapılmıştır. Yüklenici tüm test raporlarını teslim etmiştir.",
         "2. Tespit edilen eksiklikler",
         [["No.", "Açıklama", "Son tarih"], ["1", "Bodrum kattaki kablo tavası topraklanmamış", "30.04.2026"],
          ["2", "Çıkış fiderlerinin etiketlemesi eksik", "15.04.2026"], ["3", "KGK ara devresinde kalan işler", "30.04.2026"]],
         ("Dağıtım panosu", "KGK", "Kablo tavası"), "Topraklama bağlantısı eksik",
         "Şekil 1: Bodrum kat genel görünümü", "3. Sonuç",
         "Tesis, yukarıdaki eksikliklerin giderilmesi şartıyla geçici olarak kabul edilmiştir. Yeniden kontrol 18. haftada "
         "yapılacaktır. O zamana kadar sözleşme bedelinin %5'i teminat olarak tutulur.",
         "Sayfa {page} / {pages}", terms=["geçici olarak kabul", "KGK"]),
    Lang("ru", "Russian", "ПС «Северная» · Проект UW-2291 · Конфиденциально",
         "Акт приёмки – ПС «Северная»", "Дата: 14.03.2026 | № проекта: UW-2291",
         "1. Предмет приёмки",
         "Приёмка охватывает реконструкцию распределительного устройства 110 кВ, включая вторичные цепи. Работы выполнены "
         "в соответствии с позицией 4.2.7 сметы. Подрядчик передал все протоколы испытаний.",
         "2. Выявленные недостатки",
         [["№", "Описание", "Срок"], ["1", "Кабельный лоток в подвале не заземлён", "30.04.2026"],
          ["2", "Маркировка отходящих присоединений неполная", "15.04.2026"],
          ["3", "Незавершённые работы на промежуточном звене ИБП", "30.04.2026"]],
         ("Распределительный щит", "ИБП", "Кабельный лоток"), "Отсутствует заземление",
         "Рис. 1: Общий вид подвала", "3. Заключение",
         "Объект принимается условно до устранения перечисленных недостатков. Повторная проверка запланирована на 18-ю "
         "неделю. До этого момента удерживается 5 % от суммы договора в качестве гарантийного обеспечения.",
         "Страница {page} из {pages}", terms=["ПС", "ИБП", "принимается условно"]),
    Lang("uk", "Ukrainian", "ПС «Північна» · Проєкт UW-2291 · Конфіденційно",
         "Акт приймання – ПС «Північна»", "Дата: 14.03.2026 | № проєкту: UW-2291",
         "1. Предмет приймання",
         "Приймання охоплює реконструкцію розподільчого пристрою 110 кВ, включно з вторинними колами. Роботи виконано "
         "відповідно до позиції 4.2.7 кошторису. Підрядник передав усі протоколи випробувань.",
         "2. Виявлені недоліки",
         [["№", "Опис", "Термін"], ["1", "Кабельний лоток у підвалі не заземлено", "30.04.2026"],
          ["2", "Маркування відхідних приєднань неповне", "15.04.2026"],
          ["3", "Незавершені роботи на проміжній ланці ДБЖ", "30.04.2026"]],
         ("Розподільчий щит", "ДБЖ", "Кабельний лоток"), "Відсутнє заземлення",
         "Рис. 1: Загальний вигляд підвалу", "3. Висновок",
         "Об'єкт приймається умовно до усунення зазначених недоліків. Повторну перевірку заплановано на 18-й тиждень. "
         "До того часу утримується 5 % суми договору як гарантійне забезпечення.",
         "Сторінка {page} з {pages}", terms=["ДБЖ", "приймається умовно"]),
    Lang("el", "Greek", "Υποσταθμός Βορρά · Έργο UW-2291 · Εμπιστευτικό",
         "Πρωτόκολλο παραλαβής – Υποσταθμός Βορρά", "Ημερομηνία: 14/03/2026 | Αρ. έργου: UW-2291",
         "1. Αντικείμενο της παραλαβής",
         "Η παραλαβή αφορά την ανανέωση του εξοπλισμού ζεύξης 110 kV, συμπεριλαμβανομένων των δευτερευόντων συστημάτων. "
         "Οι εργασίες εκτελέστηκαν σύμφωνα με το άρθρο 4.2.7 του προϋπολογισμού. Ο ανάδοχος παρέδωσε όλες τις εκθέσεις δοκιμών.",
         "2. Διαπιστωθείσες ελλείψεις",
         [["Α/Α", "Περιγραφή", "Προθεσμία"], ["1", "Η σχάρα καλωδίων στο υπόγειο δεν είναι γειωμένη", "30/04/2026"],
          ["2", "Ελλιπής σήμανση των αναχωρήσεων", "15/04/2026"],
          ["3", "Υπολειπόμενες εργασίες στο ενδιάμεσο κύκλωμα του UPS", "30/04/2026"]],
         ("Πίνακας διανομής", "UPS", "Σχάρα καλωδίων"), "Λείπει η γείωση",
         "Σχήμα 1: Γενική άποψη του υπογείου", "3. Συμπέρασμα",
         "Η εγκατάσταση παραλαμβάνεται με επιφύλαξη μέχρι την αποκατάσταση των παραπάνω ελλείψεων. Ο επανέλεγχος έχει "
         "προγραμματιστεί για την εβδομάδα 18. Μέχρι τότε παρακρατείται το 5% του συμβατικού ποσού ως εγγύηση.",
         "Σελίδα {page} από {pages}", terms=["παραλαμβάνεται με επιφύλαξη"]),
    Lang("ar", "Arabic", "محطة التحويل الشمالية · المشروع UW-2291 · سري",
         "محضر الاستلام – محطة التحويل الشمالية", "التاريخ: 14/03/2026 | رقم المشروع: UW-2291",
         "1. نطاق الاستلام",
         "يشمل الاستلام تجديد معدات المفاتيح الكهربائية جهد 110 كيلوفولت، بما في ذلك الأنظمة الثانوية. نُفذت الأعمال "
         "وفقًا للبند 4.2.7 من جدول الكميات. سلّم المقاول جميع تقارير الاختبار.",
         "2. العيوب المكتشفة",
         [["رقم", "الوصف", "المهلة"], ["1", "حامل الكابلات في الطابق السفلي غير مؤرض", "30/04/2026"],
          ["2", "ترقيم المغذيات الخارجة غير مكتمل", "15/04/2026"], ["3", "أعمال متبقية في الدائرة الوسيطة لجهاز UPS", "30/04/2026"]],
         ("لوحة التوزيع", "UPS", "حامل الكابلات"), "التأريض مفقود",
         "الشكل 1: نظرة عامة على الطابق السفلي", "3. الخلاصة",
         "تُستلم المنشأة استلامًا مشروطًا لحين إصلاح العيوب المذكورة أعلاه. من المقرر إجراء إعادة الفحص في الأسبوع 18. "
         "وحتى ذلك الحين، يُحتجز 5% من قيمة العقد كضمان.",
         "الصفحة {page} من {pages}", rtl=True, terms=["استلامًا مشروطًا"]),
    Lang("he", "Hebrew", "תחנת המשנה צפון · פרויקט UW-2291 · סודי",
         "פרוטוקול מסירה – תחנת המשנה צפון", "תאריך: 14.03.2026 | מס' פרויקט: UW-2291",
         "1. היקף המסירה",
         "המסירה כוללת את חידוש מערך המיתוג 110 קילו-וולט, כולל המערכות המשניות. העבודות בוצעו בהתאם לסעיף 4.2.7 "
         "בכתב הכמויות. הקבלן מסר את כל דוחות הבדיקה.",
         "2. ליקויים שנמצאו",
         [["מס'", "תיאור", "מועד"], ["1", "תעלת הכבלים במרתף אינה מוארקת", "30.04.2026"],
          ["2", "סימון המזינים היוצאים אינו שלם", "15.04.2026"], ["3", "עבודות שנותרו במעגל הביניים של האל-פסק", "30.04.2026"]],
         ("לוח חלוקה", "אל-פסק", "תעלת כבלים"), "חסרה הארקה",
         "איור 1: מבט כללי על המרתף", "3. סיכום",
         "המתקן מתקבל בתנאי עד לתיקון הליקויים המפורטים לעיל. בדיקה חוזרת מתוכננת לשבוע 18. עד אז יעוכבו 5% מסכום החוזה כערבות.",
         "עמוד {page} מתוך {pages}", rtl=True, terms=["אל-פסק", "מתקבל בתנאי"]),
    Lang("hi", "Hindi", "उत्तर उपकेंद्र · परियोजना UW-2291 · गोपनीय",
         "स्वीकृति प्रोटोकॉल – उत्तर उपकेंद्र", "दिनांक: 14.03.2026 | परियोजना सं.: UW-2291",
         "1. स्वीकृति का दायरा",
         "स्वीकृति में द्वितीयक प्रणालियों सहित 110 kV स्विचगियर का नवीनीकरण शामिल है। कार्य मात्रा-सूची के मद 4.2.7 के "
         "अनुसार किया गया। ठेकेदार ने सभी परीक्षण रिपोर्टें सौंप दी हैं।",
         "2. पाए गए दोष",
         [["क्र.", "विवरण", "समय-सीमा"], ["1", "तहखाने में केबल ट्रे का अर्थिंग नहीं किया गया", "30.04.2026"],
          ["2", "आउटगोइंग फीडरों की लेबलिंग अधूरी", "15.04.2026"], ["3", "यूपीएस के डीसी लिंक पर शेष कार्य", "30.04.2026"]],
         ("वितरण बोर्ड", "यूपीएस", "केबल ट्रे"), "अर्थिंग कनेक्शन नहीं है",
         "चित्र 1: तहखाने का सामान्य दृश्य", "3. निष्कर्ष",
         "उपर्युक्त दोषों के निवारण की शर्त पर संयंत्र को सशर्त स्वीकार किया जाता है। पुनः निरीक्षण सप्ताह 18 में निर्धारित है। "
         "तब तक अनुबंध राशि का 5% प्रतिभूति के रूप में रोका जाता है।",
         "पृष्ठ {page} / {pages}", terms=["सशर्त स्वीकार", "प्रतिभूति"]),
    Lang("bn", "Bengali", "উত্তর উপকেন্দ্র · প্রকল্প UW-2291 · গোপনীয়",
         "গ্রহণ প্রতিবেদন – উত্তর উপকেন্দ্র", "তারিখ: 14.03.2026 | প্রকল্প নং: UW-2291",
         "1. গ্রহণের পরিধি",
         "গ্রহণের আওতায় রয়েছে মাধ্যমিক ব্যবস্থাসহ 110 kV সুইচগিয়ারের নবায়ন। কাজটি পরিমাণ তালিকার 4.2.7 নং আইটেম "
         "অনুযায়ী সম্পন্ন হয়েছে। ঠিকাদার সব পরীক্ষার প্রতিবেদন হস্তান্তর করেছেন।",
         "2. চিহ্নিত ত্রুটি",
         [["ক্রম", "বিবরণ", "সময়সীমা"], ["1", "বেসমেন্টের কেবল ট্রে আর্থিং করা হয়নি", "30.04.2026"],
          ["2", "বহির্গামী ফিডারের লেবেলিং অসম্পূর্ণ", "15.04.2026"], ["3", "ইউপিএসের ডিসি লিঙ্কে অবশিষ্ট কাজ", "30.04.2026"]],
         ("বিতরণ বোর্ড", "ইউপিএস", "কেবল ট্রে"), "আর্থিং সংযোগ নেই",
         "চিত্র 1: বেসমেন্টের সাধারণ দৃশ্য", "3. উপসংহার",
         "উপরের ত্রুটিগুলো সংশোধনের শর্তে স্থাপনাটি শর্তসাপেক্ষে গৃহীত হলো। পুনঃপরিদর্শন 18তম সপ্তাহে নির্ধারিত। "
         "ততদিন চুক্তিমূল্যের 5% জামানত হিসেবে আটকে রাখা হবে।",
         "পৃষ্ঠা {page} / {pages}", terms=["শর্তসাপেক্ষে গৃহীত", "জামানত"]),
    Lang("id", "Indonesian", "Gardu Induk Utara · Proyek UW-2291 · Rahasia",
         "Berita Acara Serah Terima – Gardu Induk Utara", "Tanggal: 14/03/2026 | No. proyek: UW-2291",
         "1. Lingkup serah terima",
         "Serah terima mencakup pembaruan switchgear 110 kV termasuk sistem sekunder. Pekerjaan dilaksanakan sesuai butir "
         "4.2.7 daftar kuantitas. Kontraktor telah menyerahkan seluruh laporan pengujian.",
         "2. Cacat yang ditemukan",
         [["No.", "Uraian", "Batas waktu"], ["1", "Rak kabel di ruang bawah tanah belum dibumikan", "30/04/2026"],
          ["2", "Pelabelan penyulang keluar belum lengkap", "15/04/2026"], ["3", "Sisa pekerjaan pada rangkaian antara UPS", "30/04/2026"]],
         ("Panel distribusi", "UPS", "Rak kabel"), "Sambungan pembumian tidak ada",
         "Gambar 1: Gambaran umum ruang bawah tanah", "3. Kesimpulan",
         "Instalasi diterima secara bersyarat sampai cacat di atas diperbaiki. Pemeriksaan ulang dijadwalkan pada minggu "
         "ke-18. Hingga saat itu, 5% dari nilai kontrak ditahan sebagai jaminan.",
         "Halaman {page} dari {pages}", terms=["Berita Acara Serah Terima", "diterima secara bersyarat"]),
    Lang("vi", "Vietnamese", "Trạm biến áp Bắc · Dự án UW-2291 · Mật",
         "Biên bản nghiệm thu – Trạm biến áp Bắc", "Ngày: 14/03/2026 | Số dự án: UW-2291",
         "1. Phạm vi nghiệm thu",
         "Phạm vi nghiệm thu bao gồm việc cải tạo thiết bị đóng cắt 110 kV, kể cả hệ thống nhị thứ. Công việc được thực "
         "hiện theo hạng mục 4.2.7 của bảng khối lượng. Nhà thầu đã bàn giao toàn bộ biên bản thử nghiệm.",
         "2. Các tồn tại phát hiện",
         [["STT", "Mô tả", "Thời hạn"], ["1", "Máng cáp ở tầng hầm chưa được nối đất", "30/04/2026"],
          ["2", "Ghi nhãn các ngăn lộ ra chưa đầy đủ", "15/04/2026"], ["3", "Công việc còn lại ở mạch trung gian của UPS", "30/04/2026"]],
         ("Tủ phân phối", "UPS", "Máng cáp"), "Thiếu kết nối tiếp địa",
         "Hình 1: Tổng quan tầng hầm", "3. Kết luận",
         "Công trình được nghiệm thu có điều kiện cho đến khi khắc phục các tồn tại nêu trên. Việc kiểm tra lại dự kiến vào "
         "tuần 18. Đến lúc đó, 5% giá trị hợp đồng được giữ lại làm bảo đảm.",
         "Trang {page}/{pages}", terms=["nghiệm thu có điều kiện", "tồn tại", "nhị thứ"]),
    Lang("th", "Thai", "สถานีไฟฟ้าย่อยเหนือ · โครงการ UW-2291 · ลับ",
         "บันทึกการตรวจรับงาน – สถานีไฟฟ้าย่อยเหนือ", "วันที่: 14/03/2026 | เลขที่โครงการ: UW-2291",
         "1. ขอบเขตการตรวจรับ",
         "การตรวจรับครอบคลุมการปรับปรุงอุปกรณ์สวิตช์เกียร์ 110 kV รวมถึงระบบทุติยภูมิ งานได้ดำเนินการตามรายการ 4.2.7 "
         "ของบัญชีปริมาณงาน ผู้รับจ้างได้ส่งมอบรายงานผลการทดสอบครบถ้วนแล้ว",
         "2. ข้อบกพร่องที่พบ",
         [["ลำดับ", "รายละเอียด", "กำหนดเสร็จ"], ["1", "รางเคเบิลในชั้นใต้ดินไม่ได้ต่อลงดิน", "30/04/2026"],
          ["2", "การติดป้ายฟีดเดอร์ขาออกไม่ครบถ้วน", "15/04/2026"], ["3", "งานคงค้างที่วงจรกลางของ UPS", "30/04/2026"]],
         ("ตู้จ่ายไฟ", "UPS", "รางเคเบิล"), "ไม่มีการต่อลงดิน",
         "รูปที่ 1: ภาพรวมชั้นใต้ดิน", "3. สรุป",
         "ตรวจรับงานแบบมีเงื่อนไขจนกว่าจะแก้ไขข้อบกพร่องข้างต้นแล้วเสร็จ กำหนดตรวจซ้ำในสัปดาห์ที่ 18 "
         "ระหว่างนี้จะหักเงินประกันผลงานไว้ 5% ของมูลค่าสัญญา",
         "หน้า {page} จาก {pages}", terms=["ตรวจรับงานแบบมีเงื่อนไข", "เงินประกันผลงาน"]),
    Lang("ja", "Japanese", "北変電所　プロジェクトUW-2291　社外秘",
         "受入検査報告書―北変電所", "日付：2026年3月14日｜プロジェクト番号：UW-2291",
         "1. 検査の範囲",
         "本検査は、二次系統を含む110 kV開閉装置の更新工事を対象とする。工事は数量明細書の項目4.2.7に従って実施された。"
         "請負者は全ての試験報告書を引き渡した。",
         "2. 指摘事項",
         [["No.", "内容", "期限"], ["1", "地下のケーブルラックが未接地", "2026年4月30日"],
          ["2", "引出し回線の表示が不完全", "2026年4月15日"], ["3", "UPS直流中間回路の残工事", "2026年4月30日"]],
         ("配電盤", "UPS", "ケーブルラック"), "接地接続なし",
         "図1：地下の全体図", "3. 結論",
         "上記指摘事項の是正を条件として、設備を条件付きで受け入れる。再検査は第18週に予定している。"
         "それまでの間、契約金額の5%を保証金として留保する。",
         "{page}／{pages}ページ", terms=["条件付きで受け入れる", "指摘事項", "社外秘"]),
    Lang("ko", "Korean", "북부 변전소 · 프로젝트 UW-2291 · 대외비",
         "인수 검사 보고서 – 북부 변전소", "날짜: 2026년 3월 14일 | 프로젝트 번호: UW-2291",
         "1. 검사 범위",
         "본 검사는 2차 계통을 포함한 110 kV 개폐장치의 교체 공사를 대상으로 한다. 공사는 물량내역서 항목 4.2.7에 따라 "
         "시행되었다. 시공사는 모든 시험 성적서를 인계하였다.",
         "2. 지적 사항",
         [["번호", "내용", "기한"], ["1", "지하 케이블 트레이 미접지", "2026년 4월 30일"],
          ["2", "인출 회선 표시 불완전", "2026년 4월 15일"], ["3", "UPS 직류 중간회로 잔여 공사", "2026년 4월 30일"]],
         ("배전반", "UPS", "케이블 트레이"), "접지 연결 없음",
         "그림 1: 지하 전경", "3. 결론",
         "위 지적 사항의 시정을 조건으로 설비를 조건부 인수한다. 재검사는 18주차에 예정되어 있다. "
         "그때까지 계약 금액의 5%를 하자보증금으로 유보한다.",
         "{page} / {pages} 페이지", terms=["조건부 인수", "하자보증금", "대외비"]),
    Lang("zh-Hant", "Chinese (Traditional)", "北區變電站改造工程·UW-2291·內部資料",
         "設備驗收報告——北區變電站", "日期：2026年3月14日 ｜ 項目編號：UW-2291",
         "一、驗收範圍",
         "本次驗收範圍為110千伏開關設備的更新改造，包括二次系統。施工按照工程量清單第4.2.7項執行。承包方已完整移交全部試驗報告。",
         "二、發現的缺陷",
         [["序號", "描述", "整改期限"], ["1", "地下室電纜橋架未接地", "2026年4月30日"],
          ["2", "出線間隔標識不完整", "2026年4月15日"], ["3", "UPS直流母線遺留工作", "2026年4月30日"]],
         ("配電櫃", "UPS電源", "電纜橋架"), "缺少接地連接",
         "圖1：地下室設備概覽", "三、結論",
         "設備在上述缺陷整改完成前有條件驗收。複查定於第18週進行。在此之前，保留結算金額5%的質量保證金。",
         "第 {page} 頁 共 {pages} 頁", terms=["有條件驗收", "質量保證金"]),
]

ENGLISH = """# Acceptance report – Substation North

*Running header:* Substation North · Project UW-2291 · Confidential

Date: 14 March 2026 | Project no.: UW-2291

## 1. Scope of acceptance

The acceptance covers the renewal of the 110 kV switchgear, including the secondary systems. The work was carried out \
in accordance with item 4.2.7 of the bill of quantities. The contractor has handed over all test reports.

## 2. Defects found

| No. | Description | Deadline |
|---|---|---|
| 1 | Cable tray in the basement not earthed | 30 April 2026 |
| 2 | Labelling of the outgoing feeders incomplete | 15 April 2026 |
| 3 | Remaining work on the UPS DC link (intermediate circuit) | 30 April 2026 |

*Figure:* a diagram with three boxes — **distribution board**, **UPS**, **cable tray** — joined by lines, and the note \
**"Earth connection missing"** at the top.

Fig. 1: Basement overview

## 3. Conclusion

The installation is accepted subject to the rectification of the defects listed above (a conditional acceptance — \
"with reservations"). The re-inspection is scheduled for week 18. Until then, 5% of the contract sum is retained as \
security.

*Footer:* Page 1 of 1

---

Every file in `samples/languages/` says this. Wording differs by language: the conclusion's legal term (réception \
avec réserves, collaudo con riserva, 条件付き受入, 조건부 인수…), the local abbreviation for UPS (SAI, ASI, ИБП, ДБЖ, \
KGK, אל-פסק, यूपीएस…) and the date format (14/03/2026, 14.03.2026, 2026-03-14, 2026年3月14日, 2026년 3월 14일).
"""


def diagram(lang: Lang) -> bytes:
    """The basement diagram with its labels in the language: three boxes, the connections, a note on top."""
    doc = pymupdf.open()
    page = doc.new_page(width=420, height=230)
    side = ' dir="rtl"' if lang.rtl else ""
    css = "* {font-family: sans-serif; font-size: 13pt; text-align: center;}"
    for rect, label in zip((pymupdf.Rect(15, 40, 145, 100), pymupdf.Rect(275, 40, 405, 100), pymupdf.Rect(140, 150, 280, 210)),
                           lang.labels):
        page.draw_rect(rect, color=(0.1, 0.3, 0.7), fill=(0.9, 0.94, 1), width=2)
        page.insert_htmlbox(rect + (4, 8, -4, -4), f"<p{side}>{label}</p>", css=css)
    for a, b in (((145, 70), (275, 70)), ((80, 100), (175, 150)), ((340, 100), (245, 150))):
        page.draw_line(a, b, color=(0.2, 0.2, 0.2), width=2)
    page.insert_htmlbox(pymupdf.Rect(40, 6, 380, 28), f"<p{side}>{lang.note}</p>",
                        css=css.replace("13pt", "13pt; color: #b3261e"))
    return page.get_pixmap(dpi=150).tobytes("png")


def build(lang: Lang) -> pymupdf.Document:
    blocks = [Block("title", lang.title, ""), Block("meta", lang.meta, ""), Block("h", lang.h1, ""), Block("p", lang.p1, ""),
              Block("h", lang.h2, ""), Block("table", lang.table, ""), Block("figure", "fig1.png", ""),
              Block("caption", lang.caption, ""), Block("h", lang.h3, ""), Block("p", lang.p2, "")]
    doc = flow_pdf(blocks, title=lang.title, header=lang.header, footer=lang.footer, images={"fig1.png": diagram(lang)},
                   figure_width=360, rtl=lang.rtl)
    assert len(doc) == 1, f"{lang.code}: {len(doc)} pages"
    return doc


def source_texts(lang: Lang) -> list[str]:
    """Everything on the page as text (the diagram's labels are in the picture)."""
    return [lang.header, lang.title, lang.meta, lang.h1, lang.p1, lang.h2, *(c for row in lang.table for c in row),
            lang.caption, lang.h3, lang.p2, lang.footer.format(page=1, pages=1)]


def text_layer_ok(doc: pymupdf.Document, lang: Lang) -> bool:
    """Does the PDF's text layer say what was typeset? (Shaped scripts can come back as presentation forms or
    unmapped glyphs; a right-to-left layer may come back reversed.)"""
    layer = norm(doc[0].get_text())
    return all(norm(t) in layer for t in source_texts(lang))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    (ROOT / "samples" / "reference" / "acceptance-report.en.md").write_text(ENGLISH)
    for lang in LANGS:
        doc = build(lang)
        name = f"acceptance-{lang.code}"
        scan = OUT / f"{name}-scanned.pdf"
        scan.write_bytes(scanned(doc))
        text = OUT / f"{name}.pdf"
        if text_layer_ok(doc, lang):
            text.write_bytes(pdf_bytes(doc))
            note = "text PDF + scan"
        else:
            text.unlink(missing_ok=True)
            note = "scan only (the text layer of this script doesn't round-trip)"
        print(f"{lang.code:8} {lang.name:22} {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
