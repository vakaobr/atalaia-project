# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The texts of the staff page for a field's data export and quota use (PKC-1), merged into ``staff_i18n.STRINGS``.

Same rules as ``staff_i18n.py``: pt-PT inclusive and impersonal, German with "du" and neutral nouns, Traditional Chinese
(Taiwan) with 你, full-width punctuation after Han and a half-width space between Han and Latin letters or digits.
German and Traditional Chinese were drafted by an AI model (Claude) on 2026-10-28 and are not yet reviewed by a
native-speaking player.
"""

from __future__ import annotations

PT: dict[str, str] = {
    "nav_data": "Dados e limites",
    "data_title": "Dados e limites do campo",
    "export_title": "Exportar os dados do campo",
    "export_intro": "Descarrega tudo o que este servidor guarda do campo (contas, inscrições, jogos, cenários, "
                    "registos) num ficheiro ZIP de ficheiros JSON Lines, com um manifesto e um leia-me. "
                    "Credenciais, e-mails e endereços de rede ficam de fora.",
    "export_personal": "O ficheiro tem dados pessoais: guardá-lo com o mesmo cuidado que a base de dados. O servidor "
                       "regista cada exportação, com a impressão digital SHA-256 do ficheiro.",
    "export_run": "Preparar a exportação",
    "export_working": "A preparar o ficheiro. Pode demorar um pouco.",
    "export_download": "Descarregar o ficheiro ZIP",
    "export_hash": "SHA-256:",
    "quotas_title": "Utilização e limites",
    "quotas_intro": "O que o campo usa de cada limite deste servidor alojado. Passado um limite, o servidor recusa o "
                    "que acrescentaria mais; o que já existe nunca é apagado.",
    "quotas_none": "Este servidor serve um só campo e não tem limites de utilização.",
    "quotas_refused": "Quem gere o servidor alojado é avisado quando um campo é recusado por um limite e pode "
                      "ajustá-lo.",
    "col_quota": "Recurso",
    "col_used": "Em uso",
    "col_limit": "Limite",
    "quota_no_limit": "sem limite",
    "quota_name_accounts": "Contas",
    "quota_name_scheduled_games": "Jogos agendados",
    "quota_name_registrations": "Inscrições",
    "quota_name_games": "Jogos sincronizados",
    "quota_name_atak_certs": "Certificados ATAK ativos",
    "quota_name_streams": "Ligações abertas dos controladores",
    "quota_name_stored_mb": "Espaço na base de dados (MB)",
    "e_export_running": "Já há uma exportação deste campo a ser preparada. Esperar que acabe.",
    "e_export_too_large": "O ficheiro passaria o tamanho máximo que o servidor prepara. A operação do servidor pode "
                          "exportar o campo por outra via.",
    "e_quota_exceeded": "O campo atingiu um dos seus limites de utilização, por isso o servidor recusou isto. Os "
                        "limites estão em Dados e limites.",
}

EN: dict[str, str] = {
    "nav_data": "Data and limits",
    "data_title": "The field's data and limits",
    "export_title": "Export the field's data",
    "export_intro": "Download everything this server holds of the field (accounts, registrations, games, scenarios, "
                    "logs) as a ZIP file of JSON Lines files, with a manifest and a readme. Credentials, e-mail "
                    "addresses and network addresses are left out.",
    "export_personal": "The file holds personal data: keep it as safe as the database. The server logs each export, "
                       "with the file's SHA-256.",
    "export_run": "Prepare the export",
    "export_working": "Preparing the file. This can take a while.",
    "export_download": "Download the ZIP file",
    "export_hash": "SHA-256:",
    "quotas_title": "Use and limits",
    "quotas_intro": "What the field uses of each limit of this hosted server. Past a limit the server refuses what "
                    "would add more; what already exists is never deleted.",
    "quotas_none": "This server serves one field and has no usage limits.",
    "quotas_refused": "Whoever runs the hosted server is told when a field is refused for a limit, and can adjust it.",
    "col_quota": "Resource",
    "col_used": "In use",
    "col_limit": "Limit",
    "quota_no_limit": "no limit",
    "quota_name_accounts": "Accounts",
    "quota_name_scheduled_games": "Scheduled games",
    "quota_name_registrations": "Registrations",
    "quota_name_games": "Synced games",
    "quota_name_atak_certs": "Live ATAK certificates",
    "quota_name_streams": "Open controller streams",
    "quota_name_stored_mb": "Database space (MB)",
    "e_export_running": "An export of this field is already being prepared. Wait for it to finish.",
    "e_export_too_large": "The file would pass the largest size the server prepares. The server's operator can export "
                          "the field another way.",
    "e_quota_exceeded": "The field has reached one of its usage limits, so the server refused this. The limits are on "
                        "Data and limits.",
}

DE: dict[str, str] = {
    "nav_data": "Daten und Limits",
    "data_title": "Daten und Limits des Spielfelds",
    "export_title": "Daten des Spielfelds exportieren",
    "export_intro": "Lade alles herunter, was dieser Server vom Spielfeld speichert (Konten, Anmeldungen, Spiele, "
                    "Szenarien, Protokolle), als ZIP-Datei mit JSON-Lines-Dateien, einem Manifest und einer "
                    "Lies-mich-Datei. Zugangsdaten, E-Mail-Adressen und Netzwerkadressen bleiben draußen.",
    "export_personal": "Die Datei enthält personenbezogene Daten: Bewahre sie so sicher auf wie die Datenbank. Der "
                       "Server protokolliert jeden Export mit dem SHA-256 der Datei.",
    "export_run": "Export vorbereiten",
    "export_working": "Die Datei wird vorbereitet. Das kann etwas dauern.",
    "export_download": "ZIP-Datei herunterladen",
    "export_hash": "SHA-256:",
    "quotas_title": "Nutzung und Limits",
    "quotas_intro": "Was das Spielfeld von jedem Limit dieses gehosteten Servers nutzt. Über einem Limit lehnt der "
                    "Server ab, was mehr hinzufügen würde; Vorhandenes wird nie gelöscht.",
    "quotas_none": "Dieser Server bedient nur ein Spielfeld und hat keine Nutzungslimits.",
    "quotas_refused": "Wer den gehosteten Server betreibt, wird informiert, wenn ein Spielfeld wegen eines Limits "
                      "abgelehnt wird, und kann es anpassen.",
    "col_quota": "Ressource",
    "col_used": "Belegt",
    "col_limit": "Limit",
    "quota_no_limit": "kein Limit",
    "quota_name_accounts": "Konten",
    "quota_name_scheduled_games": "Geplante Spiele",
    "quota_name_registrations": "Anmeldungen",
    "quota_name_games": "Synchronisierte Spiele",
    "quota_name_atak_certs": "Aktive ATAK-Zertifikate",
    "quota_name_streams": "Offene Controller-Verbindungen",
    "quota_name_stored_mb": "Datenbankplatz (MB)",
    "e_export_running": "Ein Export dieses Spielfelds wird schon vorbereitet. Warte, bis er fertig ist.",
    "e_export_too_large": "Die Datei würde die größte Größe überschreiten, die der Server vorbereitet. Der Betrieb "
                          "des Servers kann das Spielfeld anders exportieren.",
    "e_quota_exceeded": "Das Spielfeld hat eines seiner Nutzungslimits erreicht, deshalb hat der Server das abgelehnt. "
                        "Die Limits stehen unter Daten und Limits.",
}

ZH_TW: dict[str, str] = {
    "nav_data": "資料與額度",
    "data_title": "場地的資料與額度",
    "export_title": "匯出場地資料",
    "export_intro": "下載這台伺服器保存的場地全部資料（帳號、報名、遊戲、情境、紀錄），格式為內含 JSON Lines 檔案、"
                    "清單與說明檔的 ZIP 檔。憑證、電子郵件與網路位址不包含在內。",
    "export_personal": "檔案含有個人資料：請像保管資料庫一樣妥善保管。伺服器會記錄每次匯出，並附上檔案的 SHA-256。",
    "export_run": "準備匯出",
    "export_working": "正在準備檔案，可能需要一點時間。",
    "export_download": "下載 ZIP 檔",
    "export_hash": "SHA-256：",
    "quotas_title": "使用量與額度",
    "quotas_intro": "場地在這台託管伺服器上各項額度的使用量。超過額度後，伺服器會拒絕新增更多資料；已有的資料不會被刪除。",
    "quotas_none": "這台伺服器只服務一個場地，沒有使用額度。",
    "quotas_refused": "場地因額度被拒絕時，託管伺服器的營運者會收到通知，並可調整額度。",
    "col_quota": "項目",
    "col_used": "已用",
    "col_limit": "額度",
    "quota_no_limit": "無上限",
    "quota_name_accounts": "帳號",
    "quota_name_scheduled_games": "排定的遊戲",
    "quota_name_registrations": "報名",
    "quota_name_games": "已同步的遊戲",
    "quota_name_atak_certs": "有效的 ATAK 憑證",
    "quota_name_streams": "開啟中的控制器連線",
    "quota_name_stored_mb": "資料庫空間（MB）",
    "e_export_running": "這個場地已有一份匯出正在準備中，請等它完成。",
    "e_export_too_large": "檔案會超過伺服器可準備的大小上限。伺服器的營運者可以用其他方式匯出場地。",
    "e_quota_exceeded": "場地已達到其中一項使用額度，所以伺服器拒絕了這個動作。額度請見「資料與額度」。",
}

BY_LANGUAGE: dict[str, dict[str, str]] = {"pt": PT, "en": EN, "de": DE, "zh-tw": ZH_TW}
