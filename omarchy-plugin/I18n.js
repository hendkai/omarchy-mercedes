.pragma library

// Ordered catalogs keep the same complete key set in every supported language.
// Resolve OS regional locales (pt_BR, zh_TW, ...) to their base language.
var keys = ["checking", "login", "offline", "soc", "range", "charging", "chargeEnd", "vehicleData", "sync", "stale", "hint", "unknown", "ago", "position", "display", "left", "center", "right", "percent", "bar", "showRange", "second", "minute", "hour", "day"]
var catalogs = {
 en: ["Reading status", "Sign in", "Connector offline", "Charge", "Range", "Charging", "Charge complete", "Vehicle data", "Last sync", "Vehicle data older than {0} min", "Note", "Unknown", "{0} ago", "Position", "Display", "Left", "Center", "Right", "Percent", "Charge bar", "Show range", "s", "min", "h", "d"],
 de: ["Status wird gelesen", "Anmelden", "Connector offline", "Ladestand", "Reichweite", "Ladevorgang aktiv", "Ladeende", "Fahrzeugdaten", "Letzter Abgleich", "Fahrzeugdaten älter als {0} min", "Hinweis", "Keine Angabe", "vor {0}", "Position", "Anzeige", "Links", "Mitte", "Rechts", "Prozent", "Ladebalken", "Reichweite anzeigen", "s", "min", "h", "T"],
 fr: ["Lecture du statut", "Connexion", "Connecteur hors ligne", "Charge", "Autonomie", "Recharge en cours", "Fin de recharge", "Données du véhicule", "Dernière synchronisation", "Données du véhicule de plus de {0} min", "Remarque", "Inconnu", "il y a {0}", "Position", "Affichage", "Gauche", "Centre", "Droite", "Pourcentage", "Barre de charge", "Afficher l’autonomie", "s", "min", "h", "j"],
 es: ["Leyendo estado", "Iniciar sesión", "Conector desconectado", "Carga", "Autonomía", "Cargando", "Fin de carga", "Datos del vehículo", "Última sincronización", "Datos del vehículo de hace más de {0} min", "Nota", "Desconocido", "hace {0}", "Posición", "Visualización", "Izquierda", "Centro", "Derecha", "Porcentaje", "Barra de carga", "Mostrar autonomía", "s", "min", "h", "d"],
 it: ["Lettura dello stato", "Accedi", "Connettore offline", "Carica", "Autonomia", "Ricarica in corso", "Fine ricarica", "Dati del veicolo", "Ultima sincronizzazione", "Dati del veicolo più vecchi di {0} min", "Nota", "Sconosciuto", "{0} fa", "Posizione", "Visualizzazione", "Sinistra", "Centro", "Destra", "Percentuale", "Barra di carica", "Mostra autonomia", "s", "min", "h", "g"],
 pt: ["A ler estado", "Iniciar sessão", "Conector offline", "Carga", "Autonomia", "A carregar", "Fim da carga", "Dados do veículo", "Última sincronização", "Dados do veículo com mais de {0} min", "Nota", "Desconhecido", "há {0}", "Posição", "Visualização", "Esquerda", "Centro", "Direita", "Percentagem", "Barra de carga", "Mostrar autonomia", "s", "min", "h", "d"],
 nl: ["Status lezen", "Aanmelden", "Connector offline", "Lading", "Actieradius", "Opladen", "Opladen voltooid", "Voertuiggegevens", "Laatste synchronisatie", "Voertuiggegevens ouder dan {0} min", "Opmerking", "Onbekend", "{0} geleden", "Positie", "Weergave", "Links", "Midden", "Rechts", "Percentage", "Laadbalk", "Actieradius tonen", "s", "min", "u", "d"],
 pl: ["Odczytywanie stanu", "Zaloguj się", "Łącznik offline", "Naładowanie", "Zasięg", "Ładowanie", "Koniec ładowania", "Dane pojazdu", "Ostatnia synchronizacja", "Dane pojazdu starsze niż {0} min", "Uwaga", "Brak danych", "{0} temu", "Pozycja", "Wyświetlanie", "Lewa", "Środek", "Prawa", "Procent", "Pasek ładowania", "Pokaż zasięg", "s", "min", "godz.", "d"],
 cs: ["Načítání stavu", "Přihlásit se", "Konektor offline", "Nabití", "Dojezd", "Nabíjení", "Konec nabíjení", "Údaje vozidla", "Poslední synchronizace", "Údaje vozidla starší než {0} min", "Poznámka", "Neznámé", "před {0}", "Poloha", "Zobrazení", "Vlevo", "Uprostřed", "Vpravo", "Procenta", "Ukazatel nabití", "Zobrazit dojezd", "s", "min", "h", "d"],
 da: ["Læser status", "Log ind", "Forbindelse offline", "Ladestand", "Rækkevidde", "Oplader", "Opladning færdig", "Køretøjsdata", "Seneste synkronisering", "Køretøjsdata ældre end {0} min", "Bemærkning", "Ukendt", "for {0} siden", "Placering", "Visning", "Venstre", "Midten", "Højre", "Procent", "Ladebjælke", "Vis rækkevidde", "s", "min", "t", "d"],
 sv: ["Läser status", "Logga in", "Anslutning offline", "Laddning", "Räckvidd", "Laddar", "Laddning klar", "Fordonsdata", "Senaste synkronisering", "Fordonsdata äldre än {0} min", "Anmärkning", "Okänt", "för {0} sedan", "Position", "Visning", "Vänster", "Mitten", "Höger", "Procent", "Laddningsstapel", "Visa räckvidd", "s", "min", "h", "d"],
 nb: ["Leser status", "Logg inn", "Tilkobling frakoblet", "Ladenivå", "Rekkevidde", "Lader", "Lading ferdig", "Kjøretøydata", "Siste synkronisering", "Kjøretøydata eldre enn {0} min", "Merknad", "Ukjent", "for {0} siden", "Plassering", "Visning", "Venstre", "Midten", "Høyre", "Prosent", "Ladestolpe", "Vis rekkevidde", "s", "min", "t", "d"],
 fi: ["Luetaan tilaa", "Kirjaudu", "Yhdistin offline", "Varaus", "Toimintamatka", "Ladataan", "Lataus valmis", "Ajoneuvotiedot", "Viimeisin synkronointi", "Ajoneuvotiedot yli {0} min vanhoja", "Huomautus", "Ei tietoa", "{0} sitten", "Sijainti", "Näyttö", "Vasen", "Keskellä", "Oikea", "Prosentti", "Latauspalkki", "Näytä toimintamatka", "s", "min", "h", "pv"],
 tr: ["Durum okunuyor", "Oturum aç", "Bağlayıcı çevrimdışı", "Şarj", "Menzil", "Şarj oluyor", "Şarj bitişi", "Araç verileri", "Son eşitleme", "Araç verileri {0} dakikadan eski", "Not", "Bilinmiyor", "{0} önce", "Konum", "Görünüm", "Sol", "Orta", "Sağ", "Yüzde", "Şarj çubuğu", "Menzili göster", "sn", "dk", "sa", "g"],
 uk: ["Читання стану", "Увійти", "З’єднувач офлайн", "Заряд", "Запас ходу", "Заряджання", "Завершення заряджання", "Дані автомобіля", "Остання синхронізація", "Дані автомобіля старші за {0} хв", "Примітка", "Немає даних", "{0} тому", "Положення", "Відображення", "Ліворуч", "По центру", "Праворуч", "Відсоток", "Смуга заряду", "Показувати запас ходу", "с", "хв", "год", "д"],
 ru: ["Чтение состояния", "Войти", "Соединитель офлайн", "Заряд", "Запас хода", "Зарядка", "Завершение зарядки", "Данные автомобиля", "Последняя синхронизация", "Данные автомобиля старше {0} мин", "Примечание", "Нет данных", "{0} назад", "Положение", "Отображение", "Слева", "По центру", "Справа", "Процент", "Полоса заряда", "Показывать запас хода", "с", "мин", "ч", "д"],
 ja: ["状態を読み込み中", "ログイン", "コネクターはオフライン", "充電率", "航続距離", "充電中", "充電完了", "車両データ", "最終同期", "車両データは{0}分以上前", "注記", "不明", "{0}前", "位置", "表示", "左", "中央", "右", "パーセント", "充電バー", "航続距離を表示", "秒", "分", "時間", "日"],
 ko: ["상태 읽는 중", "로그인", "커넥터 오프라인", "충전량", "주행 가능 거리", "충전 중", "충전 완료", "차량 데이터", "마지막 동기화", "차량 데이터가 {0}분 이상 지남", "참고", "알 수 없음", "{0} 전", "위치", "표시", "왼쪽", "가운데", "오른쪽", "백분율", "충전 막대", "주행 가능 거리 표시", "초", "분", "시간", "일"],
 zh: ["正在读取状态", "登录", "连接器离线", "电量", "续航里程", "正在充电", "充电完成", "车辆数据", "上次同步", "车辆数据已超过{0}分钟", "提示", "未知", "{0}前", "位置", "显示", "左侧", "居中", "右侧", "百分比", "电量条", "显示续航里程", "秒", "分钟", "小时", "天"],
 ar: ["جارٍ قراءة الحالة", "تسجيل الدخول", "الموصل غير متصل", "الشحن", "المدى", "جارٍ الشحن", "اكتمال الشحن", "بيانات السيارة", "آخر مزامنة", "بيانات السيارة أقدم من {0} دقيقة", "ملاحظة", "غير معروف", "منذ {0}", "الموضع", "العرض", "اليسار", "الوسط", "اليمين", "النسبة المئوية", "شريط الشحن", "إظهار المدى", "ث", "د", "س", "ي"]
}
function language(localeName) {
 var base = String(localeName || "en").toLowerCase().split(/[-_.@]/)[0]
 if (base === "no") base = "nb"
 return catalogs[base] ? base : "en"
}
function text(localeName, key, args) {
 var index = keys.indexOf(key)
 if (index < 0) return key
 var result = catalogs[language(localeName)][index] || catalogs.en[index]
 for (var i = 0; args && i < args.length; i++) result = result.split("{" + i + "}").join(String(args[i]))
 return result
}
