using System.Collections.Generic;

namespace UniversalDownloader.Avalonia;

/// <summary>
/// Bilingual English (LTR) and Arabic (RTL) UI string catalog for the Avalonia desktop application.
/// </summary>
public static class Localization
{
    private static readonly Dictionary<string, string> En = new()
    {
        // App Frame & Navigation
        ["AppTitle"] = "Universal Media Downloader",
        ["CheckUpdates"] = "Check Updates",
        ["QuickHud"] = "Quick HUD",
        ["LangToggle"] = "عربي",

        // Theme Names
        ["ThemeDefault"] = "Default Dark",
        ["ThemeAmoled"] = "AMOLED Black",
        ["ThemeNord"] = "Nord Frost",
        ["ThemeCyberpunk"] = "Cyberpunk",
        ["ThemeCatppuccin"] = "Catppuccin",
        ["ThemeEmerald"] = "Emerald",

        // Tabs
        ["TabDownload"] = "Download",
        ["TabQueue"] = "Queue",
        ["TabStreams"] = "Streams",
        ["TabHistory"] = "History",
        ["TabSubscriptions"] = "Subscriptions",
        ["TabLogs"] = "Console Logs",
        ["TabPrivacy"] = "Privacy",
        ["TabCredits"] = "Credits",

        // Download Tab
        ["MediaUrl"] = "Media URL",
        ["UrlWatermark"] = "Paste video, audio, or playlist URL here...",
        ["Paste"] = "Paste",
        ["InspectStreams"] = "Inspect Streams",
        ["DownloadOptions"] = "Download Options",
        ["Quality"] = "Quality",
        ["Codec"] = "Codec Preference",
        ["Fragments"] = "Fragments",
        ["SaveDirectory"] = "Save Directory",
        ["Browse"] = "Browse...",
        ["Open"] = "Open",
        ["BrowserCookies"] = "Browser Cookies",
        ["CookiesFile"] = "Cookies File (cookies.txt)",
        ["WebLogin"] = "Web Login",
        ["PasteCookies"] = "Paste Cookies",
        ["EmbedMetadata"] = "Embed Metadata",
        ["EmbedCoverArt"] = "Embed Cover Art",
        ["EmbedSubtitles"] = "Embed Subtitles",
        ["SaveThumbnail"] = "Save Thumbnail File",
        ["MinimizeToTray"] = "Minimize to System Tray on Close",
        ["MinimizeToTrayTip"] = "When enabled, clicking the window close button minimizes Universal Downloader to the Windows notification tray instead of exiting.",
        ["TrayMinimizedTitle"] = "Universal Media Downloader",
        ["TrayMinimizedNotification"] = "App minimized to the system tray. Universal Downloader continues running in the background.",
        ["LinkDetectedNotificationTitle"] = "New Link Detected",
        ["LinkDetectedNotificationMessage"] = "Ready to download: {0}",
        ["AdvancedHeader"] = "Clip Trimmer, Playlist Selection & SponsorBlock (Advanced)",
        ["StartTime"] = "Start Time",
        ["EndTime"] = "End Time",
        ["PlaylistItems"] = "Playlist Items",
        ["SponsorBlock"] = "Remove SponsorBlock Segments (sponsor, intro, outro, selfpromo)",
        ["StartDownload"] = "Start Download",
        ["ProfilePic"] = "Profile Pic",
        ["AddToQueue"] = "+ Add to Queue",
        ["Cancel"] = "Cancel",
        ["LiveTerminal"] = "Live Terminal Output",
        ["CopyOutput"] = "Copy Output",
        ["VerifiedBadge"] = "VERIFIED",

        // Queue Tab
        ["QueueHeader"] = "Batch Download Queue",
        ["QueueParallel"] = "Parallel:",
        ["QueueBatchWatermark"] = "Paste multiple URLs here (one per line) to add to the queue...",
        ["QueueAddUrls"] = "+ Add URLs",
        ["QueueSchedule"] = "Schedule:",
        ["QueueBatterySaver"] = "Pause on battery",
        ["StartQueue"] = "Start Queue",
        ["Stop"] = "Stop",
        ["ClearCompleted"] = "Clear Completed",

        // Streams Tab
        ["StreamsStatusDefault"] = "Inspect a media URL on the Download tab to view all formats.",
        ["StreamsInspecting"] = "Inspecting available video & audio streams...",
        ["RefreshStreams"] = "Refresh Streams",
        ["DownloadStream"] = "Download",
        ["AddAllToQueue"] = "+ Add All to Queue",
        ["LoadAllQualities"] = "Load All Qualities",
        ["SupportedQualities"] = "Qualities:",

        // History Tab
        ["HistorySearch"] = "Search",
        ["HistorySearchWatermark"] = "Search history...",
        ["HistoryRefresh"] = "Refresh",
        ["HistoryClearAll"] = "Clear All",
        ["HistoryPlay"] = "Play",
        ["HistoryFolder"] = "Folder",
        ["MiniPlayerExternal"] = "External",

        // Subscriptions Tab
        ["SubscriptionUrlWatermark"] = "Channel or playlist URL to auto-track (e.g. https://www.youtube.com/@channel)...",
        ["SubscriptionAudio"] = "Audio (MP3)",
        ["SubscriptionQualityLabel"] = "Quality:",
        ["SubscriptionMaxSyncLabel"] = "Max Sync:",
        ["SubscriptionSubscribe"] = "Subscribe",
        ["SubscriptionSyncAll"] = "Sync All",
        ["SubscriptionSyncing"] = "Syncing...",
        ["SubscriptionUnsubscribe"] = "Unsubscribe",

        // Logs Tab
        ["BackendLogs"] = "Backend Engine Logs",
        ["AutoScroll"] = "Auto-Scroll",
        ["FilterLogsWatermark"] = "Search / filter logs...",
        ["SaveLogs"] = "Save Logs",
        ["CopyAll"] = "Copy All",
        ["Clear"] = "Clear",
        ["PopOut"] = "Pop Out",

        // Privacy Tab
        ["PrivacyTitle"] = "Privacy & Data Transparency",
        ["PrivacySubtitle"] = "Universal Media Downloader is built with privacy as a foundational principle. We guarantee 100% open, inspectable telemetry with zero personal data collection.",
        ["PrivacyGuaranteesHeader"] = "Our Privacy Guarantees",
        ["PrivacyGuarantee1"] = "• Zero Activity Tracking: Downloaded URLs, video titles, and file contents are strictly processed on your device and are never sent anywhere.",
        ["PrivacyGuarantee2"] = "• Zero Personal Identity: No IP addresses, usernames, accounts, machine hostnames, or credentials are collected or stored.",
        ["PrivacyGuarantee3"] = "• Purely Anonymous Metrics: Heartbeats and crash traces use a locally-generated random UUIDv4.",
        ["PrivacyGuarantee4"] = "• Full GDPR Compliance: You can opt out completely or request full remote deletion of this install ID at any time.",
        ["TelemetryControlsHeader"] = "Telemetry & Diagnostics Controls",
        ["OptOutTelemetry"] = "Disable anonymous heartbeats and crash reporting (--no-telemetry)",
        ["ResetInstallId"] = "Reset Anonymous Device ID",
        ["GdprWipe"] = "GDPR Remote Data Wipe",
        ["InspectDiagnosticHeader"] = "Inspect Exact Diagnostic Data Sent to Server",
        ["InspectDiagnosticSubtitle"] = "Only high-level device specifications are transmitted (OS name, RAM, CPU architecture, screen resolution, locale, and optional friend referral tag):",
        ["TelemetryStatusActive"] = "Status: Telemetry is active (Anonymous Heartbeat & Crash Diagnostics)",
        ["TelemetryStatusDisabled"] = "Status: Telemetry is disabled (Opted Out)",

        // Credits Tab
        ["AuthorRole"] = "Creator, Architect & Lead Developer",
        ["AuthorBio"] = "Created and actively engineered Universal Media Downloader to provide a fast, private, ad-free, and open-source media downloading suite across Windows, macOS, Linux, and Android.",
        ["AuthorGithub"] = "GitHub Profile",
        ["AuthorRepo"] = "Star on GitHub",
        ["AuthorIssues"] = "Report Issue",
        ["AuthorEmail"] = "Contact Author",
        ["AboutUmdHeader"] = "About Universal Media Downloader",
        ["AboutUmdText"] = "Universal Media Downloader was built from the ground up to solve common frustrations with web media tools: eliminating intrusive ads, trackers, suspicious redirects, and paywalls. Every capability runs 100% locally on your machine.",
        ["OpenSourceTechHeader"] = "Open-Source Technologies & Acknowledgments",
        ["LicenseFooter"] = "© 2024-2026 Anthony Gaius. Distributed under the MIT Open Source License.",

        // Quick HUD
        ["QuickHudTitle"] = "Quick Download HUD",
        ["QuickHudHeader"] = "Quick Download HUD",
        ["QuickHudSubtitle"] = "Instant download or queue from anywhere (Ctrl+Shift+D)",
        ["QuickHudUrlWatermark"] = "Paste video/playlist URL here...",
        ["QuickHudFormatQuality"] = "Format & Quality:",
        ["QuickHudPreset"] = "Social / Device Preset:",
        ["QuickHudDownloadVideo"] = "Download Video",
        ["QuickHudDownloadAudio"] = "Download Audio",
        ["QuickHudAddToQueue"] = "Add to Queue",
        ["QuickHudTip"] = "Tip: Press Enter to download video immediately, or Esc to dismiss.",
        ["QuickHudDismiss"] = "Dismiss",

        // General Status
        ["Ready"] = "Ready",
    };

    private static readonly Dictionary<string, string> Ar = new()
    {
        // App Frame & Navigation
        ["AppTitle"] = "المحمل الشامل للوسائط",
        ["CheckUpdates"] = "التحقق من التحديثات",
        ["QuickHud"] = "التحميل السريع",
        ["LangToggle"] = "EN",

        // Theme Names
        ["ThemeDefault"] = "الوضع الداكن الافتراضي",
        ["ThemeAmoled"] = "أسود AMOLED",
        ["ThemeNord"] = "نورد الجليدي",
        ["ThemeCyberpunk"] = "سايبربانك",
        ["ThemeCatppuccin"] = "كاتبوشين",
        ["ThemeEmerald"] = "الزمرد",

        // Tabs
        ["TabDownload"] = "التحميل",
        ["TabQueue"] = "قائمة الانتظار",
        ["TabStreams"] = "الجودات والصيغ",
        ["TabHistory"] = "السجل",
        ["TabSubscriptions"] = "الاشتراكات",
        ["TabLogs"] = "سجل التشغيل",
        ["TabPrivacy"] = "الخصوصية",
        ["TabCredits"] = "المساهمون",

        // Download Tab
        ["MediaUrl"] = "رابط الفيديو أو القائمة",
        ["UrlWatermark"] = "الصق رابط الفيديو أو الصوت أو قائمة التشغيل هنا...",
        ["Paste"] = "لصق",
        ["InspectStreams"] = "فحص الجودات",
        ["DownloadOptions"] = "خيارات التحميل",
        ["Quality"] = "الجودة",
        ["Codec"] = "ترميز الفيديو (Codec)",
        ["Fragments"] = "عدد الأجزاء المتوازية",
        ["SaveDirectory"] = "مجلد الحفظ",
        ["Browse"] = "استعراض...",
        ["Open"] = "فتح",
        ["BrowserCookies"] = "ملفات تعريف المتصفح",
        ["CookiesFile"] = "ملف الكوكيز (cookies.txt)",
        ["WebLogin"] = "تسجيل دخول المتصفح",
        ["PasteCookies"] = "لصق الكوكيز",
        ["EmbedMetadata"] = "تضمين البيانات الوصفية",
        ["EmbedCoverArt"] = "تضمين الصورة المصغرة",
        ["EmbedSubtitles"] = "تضمين الترجمة",
        ["SaveThumbnail"] = "حفظ الصورة المصغرة كملف",
        ["MinimizeToTray"] = "تصغير لشريط المهام عند الإغلاق",
        ["MinimizeToTrayTip"] = "عند التفعيل، يؤدي النقر على زر إغلاق النافذة إلى تصغير البرنامج إلى شريط النظام بدلاً من الخروج.",
        ["TrayMinimizedTitle"] = "برنامج التحميل الشامل",
        ["TrayMinimizedNotification"] = "تم تصغير البرنامج إلى شريط النظام، ويستمر بالعمل في الخلفية.",
        ["LinkDetectedNotificationTitle"] = "تم اكتشاف رابط جديد",
        ["LinkDetectedNotificationMessage"] = "جاهز للتحميل: {0}",
        ["AdvancedHeader"] = "قص الفيديو واختيار عناصر القائمة وحذف الإعلانات (متقدم)",
        ["StartTime"] = "وقت البداية",
        ["EndTime"] = "وقت النهاية",
        ["PlaylistItems"] = "عناصر القائمة",
        ["SponsorBlock"] = "حذف المقاطع الدعائية تلقائياً (SponsorBlock)",
        ["StartDownload"] = "بدء التحميل",
        ["ProfilePic"] = "صورة البروفايل",
        ["AddToQueue"] = "+ إضافة للقائمة",
        ["Cancel"] = "إلغاء",
        ["LiveTerminal"] = "مخرجات المحرك المباشرة",
        ["CopyOutput"] = "نسخ المخرجات",
        ["VerifiedBadge"] = "موثّق",

        // Queue Tab
        ["QueueHeader"] = "قائمة التحميل المجمّع",
        ["QueueParallel"] = "المتوازي:",
        ["QueueBatchWatermark"] = "الصق روابط متعددة هنا (رابط بكل سطر) لإضافتها إلى القائمة...",
        ["QueueAddUrls"] = "+ إضافة الروابط",
        ["QueueSchedule"] = "جدولة:",
        ["QueueBatterySaver"] = "إيقاف مؤقت عند العمل بالبطارية",
        ["StartQueue"] = "بدء القائمة",
        ["Stop"] = "إيقاف",
        ["ClearCompleted"] = "مسح المكتمل",

        // Streams Tab
        ["StreamsStatusDefault"] = "افحص رابط وسائط في تبويب التحميل لعرض جميع الصيغ والجودات المتاحة.",
        ["StreamsInspecting"] = "جاري فحص جميع مسارات الفيديو والصوت المتاحة...",
        ["RefreshStreams"] = "تحديث الجودات",
        ["DownloadStream"] = "تحميل",
        ["AddAllToQueue"] = "+ إضافة الكل لقائمة الانتظار",
        ["LoadAllQualities"] = "تحميل جميع الجودات",
        ["SupportedQualities"] = "الجودات:",

        // History Tab
        ["HistorySearch"] = "بحث",
        ["HistorySearchWatermark"] = "بحث في سجل التحميلات...",
        ["HistoryRefresh"] = "تحديث",
        ["HistoryClearAll"] = "مسح الكل",
        ["HistoryPlay"] = "تشغيل",
        ["HistoryFolder"] = "المجلد",
        ["MiniPlayerExternal"] = "المشغل الخارجي",

        // Subscriptions Tab
        ["SubscriptionUrlWatermark"] = "رابط القناة أو قائمة التشغيل للمتابعة التلقائية (مثال: https://www.youtube.com/@channel)...",
        ["SubscriptionAudio"] = "صوت (MP3)",
        ["SubscriptionQualityLabel"] = "الجودة:",
        ["SubscriptionMaxSyncLabel"] = "الحد الأقصى للمزامنة:",
        ["SubscriptionSubscribe"] = "اشتراك",
        ["SubscriptionSyncAll"] = "مزامنة الكل",
        ["SubscriptionSyncing"] = "جاري المزامنة...",
        ["SubscriptionUnsubscribe"] = "إلغاء الاشتراك",

        // Logs Tab
        ["BackendLogs"] = "سجلات المحرك الكاملة",
        ["AutoScroll"] = "تمرير تلقائي",
        ["FilterLogsWatermark"] = "بحث وتصفية السجلات...",
        ["SaveLogs"] = "حفظ السجلات",
        ["CopyAll"] = "نسخ الكل",
        ["Clear"] = "مسح",
        ["PopOut"] = "نافذة منفصلة",

        // Privacy Tab
        ["PrivacyTitle"] = "الخصوصية وشفافية البيانات",
        ["PrivacySubtitle"] = "تم بناء المحمل الشامل على مبدأ أساسي هو حماية الخصوصية. نضمن قياسات برمجية مفتوحة وقابلة للفحص بنسبة 100% بدون أي جمع لبيانات شخصية.",
        ["PrivacyGuaranteesHeader"] = "ضمانات الخصوصية لدينا",
        ["PrivacyGuarantee1"] = "• انعدام تام لتتبع النشاط: الروابط المحمّلة وعناوين الفيديوهات ومحتويات الملفات تُعالج محلياً على جهازك فقط ولا تُرسل مطلقاً لأي خادم خارجي.",
        ["PrivacyGuarantee2"] = "• انعدام جمع الهوية الشخصية: لا يتم جمع أو حفظ عناوين IP أو أسماء المستخدمين أو الحسابات أو أسماء الأجهزة أو كلمات المرور.",
        ["PrivacyGuarantee3"] = "• قياسات مجهولة المصدر بالكامل: نبضات التحقق وسجلات الأعطال تستخدم معرّف UUIDv4 عشوائي يتم إنشاؤه محلياً على جهازك.",
        ["PrivacyGuarantee4"] = "• امتثال كامل للائحة حماية البيانات العامة (GDPR): يمكنك إلغاء الاشتراك تماماً أو طلب حذف بيانات التثبيت عن بعد في أي وقت.",
        ["TelemetryControlsHeader"] = "خيارات القياسات والتشخيص",
        ["OptOutTelemetry"] = "تعطيل نبضات النشاط وتقارير الأعطال المجهولة (--no-telemetry)",
        ["ResetInstallId"] = "إعادة تعيين معرّف الجهاز المجهول",
        ["GdprWipe"] = "مسح البيانات عن بُعد (GDPR)",
        ["InspectDiagnosticHeader"] = "فحص البيانات التشخيصية الدقيقة المرسلة للخادم",
        ["InspectDiagnosticSubtitle"] = "يتم إرسال مواصفات الجهاز العامة فقط (نظام التشغيل، الذاكرة العشوائية، معمارية المعالج، دقة الشاشة، واللغة):",
        ["TelemetryStatusActive"] = "الحالة: القياسات التشخيصية نشطة بمعرّف مجهول (نبضات التحقق وتشخيص الأعطال)",
        ["TelemetryStatusDisabled"] = "الحالة: تم تعطيل القياسات التشخيصية (تم إلغاء الاشتراك)",

        // Credits Tab
        ["AuthorRole"] = "المبتكر، المهندس المعماري والمطور الرئيسي",
        ["AuthorBio"] = "ابتكر وطوّر المحمل الشامل للوسائط لتوفير حزمة تنزيل وسائط سريعة، خاصة، خالية من الإعلانات ومفتوحة المصدر عبر أنظمة ويندوز وماك ولينكس وأندرويد.",
        ["AuthorGithub"] = "الملف الشخصي على GitHub",
        ["AuthorRepo"] = "نجمة على GitHub",
        ["AuthorIssues"] = "الإبلاغ عن مشكلة",
        ["AuthorEmail"] = "مراسلة المطور",
        ["AboutUmdHeader"] = "عن المحمل الشامل للوسائط",
        ["AboutUmdText"] = "تم بناء المحمل الشامل للوسائط من الصفر لحل المشكلات الشائعة في أدوات الويب: القضاء على الإعلانات المزعجة، برامج التتبع، عمليات إعادة التوجيه المشبوهة، وجدران الدفع. تعمل جميع الميزات محلياً 100% على جهازك.",
        ["OpenSourceTechHeader"] = "التقنيات مفتوحة المصدر والشكر والتقدير",
        ["LicenseFooter"] = "© 2024-2026 أنطوني غايوس. مرخص بموجب رخصة MIT مفتوحة المصدر.",

        // Quick HUD
        ["QuickHudTitle"] = "شاشة التحميل السريع",
        ["QuickHudHeader"] = "شاشة التحميل السريع",
        ["QuickHudSubtitle"] = "تحميل فوري أو إضافة لقائمة الانتظار من أي مكان (Ctrl+Shift+D)",
        ["QuickHudUrlWatermark"] = "الصق رابط الفيديو أو القائمة هنا...",
        ["QuickHudFormatQuality"] = "الصيغة والجودة:",
        ["QuickHudPreset"] = "إعداد مسبق للمنصات / الأجهزة:",
        ["QuickHudDownloadVideo"] = "تحميل فيديو",
        ["QuickHudDownloadAudio"] = "تحميل صوت",
        ["QuickHudAddToQueue"] = "إضافة للقائمة",
        ["QuickHudTip"] = "تلميح: اضغط Enter لتحميل الفيديو فوراً، أو Esc للإغلاق.",
        ["QuickHudDismiss"] = "إغلاق",

        // General Status
        ["Ready"] = "جاهز",
    };

    public static string Get(string lang, string key)
    {
        var map = lang == "ar" ? Ar : En;
        return map.TryGetValue(key, out var val) ? val : (En.TryGetValue(key, out var fallback) ? fallback : key);
    }
}
