"""GUI translations: English (source), Swedish, German.

Strings are looked up by their English text, so untranslated text falls back to
English. Placeholders use ``str.format`` names: ``tr("Connected: {identity}",
identity=...)``. tests/test_i18n.py checks that every ``tr("...")`` literal in the
GUI has a Swedish and a German entry.
"""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QLocale, QTranslator

LANGUAGES = {"en": "English", "sv": "Svenska", "de": "Deutsch"}
DEFAULT = "en"

_current = DEFAULT
_qt_translator: QTranslator | None = None

# English -> {language: translation}
STRINGS: dict[str, dict[str, str]] = {
    # connection bar
    "Port:": {"sv": "Port:", "de": "Port:"},
    "Refresh": {"sv": "Uppdatera", "de": "Aktualisieren"},
    "Connect": {"sv": "Anslut", "de": "Verbinden"},
    "Disconnect": {"sv": "Koppla från", "de": "Trennen"},
    "Poll:": {"sv": "Mätintervall:", "de": "Abfrage:"},
    "Output off on exit": {
        "sv": "Stäng av utgången vid avslut",
        "de": "Ausgang beim Beenden aus",
    },
    "Simulator": {"sv": "Simulator", "de": "Simulator"},
    "&Language": {"sv": "&Språk", "de": "&Sprache"},
    "&Settings": {"sv": "&Inställningar", "de": "&Einstellungen"},
    "Confirm before storing a memory": {
        "sv": "Bekräfta innan ett minne sparas",
        "de": "Vor dem Speichern eines Speicherplatzes nachfragen",
    },
    "Don't show again": {"sv": "Visa inte igen", "de": "Nicht mehr anzeigen"},
    "Max": {"sv": "Max", "de": "Max"},
    "Reset": {"sv": "Nollställ", "de": "Zurücksetzen"},
    "Reset the maximum values": {
        "sv": "Nollställ maxvärdena",
        "de": "Maximalwerte zurücksetzen",
    },
    # output / readouts
    "Output": {"sv": "Utgång", "de": "Ausgang"},
    "OFF": {"sv": "AV", "de": "AUS"},
    "Set: {volts} / {amps}": {"sv": "Inställt: {volts} / {amps}", "de": "Soll: {volts} / {amps}"},
    # control
    "Control": {"sv": "Styrning", "de": "Steuerung"},
    "Voltage": {"sv": "Spänning", "de": "Spannung"},
    "Current limit": {"sv": "Strömgräns", "de": "Strombegrenzung"},
    "Applied immediately": {"sv": "Gäller direkt", "de": "Wird sofort übernommen"},
    "Output ON": {"sv": "Utgång PÅ", "de": "Ausgang EIN"},
    "Output OFF": {"sv": "Utgång AV", "de": "Ausgang AUS"},
    "OCP (cut output at current limit)": {
        "sv": "OCP (bryt utgången vid strömgränsen)",
        "de": "OCP (Ausgang bei Strombegrenzung abschalten)",
    },
    "OVP (cut output above voltage)": {
        "sv": "OVP (bryt utgången vid överspänning)",
        "de": "OVP (Ausgang bei Überspannung abschalten)",
    },
    # memories
    "Memories": {"sv": "Minnen", "de": "Speicher"},
    "Recall": {"sv": "Hämta", "de": "Abrufen"},
    "Store": {"sv": "Spara", "de": "Speichern"},
    "Load into the setpoints (the output stays as it is)": {
        "sv": "Ladda in i inställningarna (utgången påverkas inte)",
        "de": "In die Sollwerte laden (der Ausgang bleibt unverändert)",
    },
    "Store the Voltage / Current limit fields above into this memory": {
        "sv": "Spara fälten Spänning / Strömgräns ovan i det här minnet",
        "de": "Die Felder Spannung / Strombegrenzung oben in diesem Speicher ablegen",
    },
    "Read memories": {"sv": "Läs minnen", "de": "Speicher lesen"},
    "Reads M1-M5 by recalling each; only with output off": {
        "sv": "Läser M1–M5 genom att hämta vart och ett; bara med utgången av",
        "de": "Liest M1–M5 durch Abrufen; nur bei ausgeschaltetem Ausgang",
    },
    "not saved yet – saved when output is turned off": {
        "sv": "inte sparat än – sparas när utgången stängs av",
        "de": "noch nicht gespeichert – wird beim Ausschalten des Ausgangs gespeichert",
    },
    "saving…": {"sv": "sparar…", "de": "wird gespeichert…"},
    "saving failed – previous value shown": {
        "sv": "sparningen misslyckades – tidigare värde visas",
        "de": "Speichern fehlgeschlagen – vorheriger Wert angezeigt",
    },
    "M{slot} is saved when you turn the output off "
    "(the supply cannot store a memory while the output is on)": {
        "sv": "M{slot} sparas när du stänger av utgången "
        "(aggregatet kan inte spara ett minne medan utgången är på)",
        "de": "M{slot} wird gespeichert, sobald Sie den Ausgang ausschalten "
        "(das Netzgerät kann bei eingeschaltetem Ausgang keinen Speicher schreiben)",
    },
    "Store memory": {"sv": "Spara minne", "de": "Speicher schreiben"},
    "Overwrite M{slot} with {values}?": {
        "sv": "Skriva över M{slot} med {values}?",
        "de": "M{slot} mit {values} überschreiben?",
    },
    "The supply can only store with the output off, "
    "so this is written when you switch the output off.": {
        "sv": "Aggregatet kan bara spara med utgången avstängd, "
        "så minnet skrivs när du stänger av utgången.",
        "de": "Das Netzgerät kann nur bei ausgeschaltetem Ausgang speichern; "
        "der Speicher wird geschrieben, sobald Sie den Ausgang ausschalten.",
    },
    # plots
    "Window:": {"sv": "Tidsfönster:", "de": "Zeitfenster:"},
    "All": {"sv": "Allt", "de": "Alle"},
    "Pause": {"sv": "Pausa", "de": "Pause"},
    "Resume": {"sv": "Fortsätt", "de": "Fortsetzen"},
    "Clear": {"sv": "Rensa", "de": "Löschen"},
    "Export CSV…": {"sv": "Exportera CSV…", "de": "CSV exportieren…"},
    "Log to CSV…": {"sv": "Logga till CSV…", "de": "In CSV protokollieren…"},
    "Logging: {name}": {"sv": "Loggar: {name}", "de": "Protokoll: {name}"},
    "Power": {"sv": "Effekt", "de": "Leistung"},
    "Current": {"sv": "Ström", "de": "Strom"},
    "Time": {"sv": "Tid", "de": "Zeit"},
    "Export samples": {"sv": "Exportera mätvärden", "de": "Messwerte exportieren"},
    "Log samples to": {"sv": "Logga mätvärden till", "de": "Messwerte protokollieren nach"},
    "Exported {count} samples to {path}": {
        "sv": "Exporterade {count} mätvärden till {path}",
        "de": "{count} Messwerte nach {path} exportiert",
    },
    # status bar
    "Not connected": {"sv": "Inte ansluten", "de": "Nicht verbunden"},
    "Connecting to {port}…": {"sv": "Ansluter till {port}…", "de": "Verbinde mit {port}…"},
    "Connected: {identity}": {"sv": "Ansluten: {identity}", "de": "Verbunden: {identity}"},
    "Disconnected": {"sv": "Frånkopplad", "de": "Getrennt"},
    "Error: {message}": {"sv": "Fel: {message}", "de": "Fehler: {message}"},
    # worker messages
    "not connected": {"sv": "inte ansluten", "de": "nicht verbunden"},
    "connect failed: {error}": {
        "sv": "anslutningen misslyckades: {error}",
        "de": "Verbindung fehlgeschlagen: {error}",
    },
    "switch the output off before reading memories": {
        "sv": "stäng av utgången innan minnena läses",
        "de": "vor dem Lesen der Speicher den Ausgang ausschalten",
    },
    "M{slot} is unknown; switch the output off and read the memories first": {
        "sv": "M{slot} är okänt; stäng av utgången och läs minnena först",
        "de": "M{slot} ist unbekannt; Ausgang ausschalten und zuerst die Speicher lesen",
    },
    "storing M{slot} failed: {error}": {
        "sv": "sparningen av M{slot} misslyckades: {error}",
        "de": "Speichern von M{slot} fehlgeschlagen: {error}",
    },
    "{slots} not stored: output was still on": {
        "sv": "{slots} sparades inte: utgången var fortfarande på",
        "de": "{slots} nicht gespeichert: Ausgang war noch eingeschaltet",
    },
}


def tr(text: str, **fmt: object) -> str:
    translated = STRINGS.get(text, {}).get(_current, text)
    return translated.format(**fmt) if fmt else translated


def current() -> str:
    return _current


def system_language() -> str:
    code = QLocale.system().name()[:2]
    return code if code in LANGUAGES else DEFAULT


def set_language(code: str) -> None:
    """Switch the language. Also loads Qt's own translations (standard dialog buttons)."""
    global _current, _qt_translator
    if code not in LANGUAGES:
        raise ValueError(f"unsupported language {code!r}; choose from {', '.join(LANGUAGES)}")
    _current = code
    app = QCoreApplication.instance()
    if app is None:
        return
    if _qt_translator is not None:
        app.removeTranslator(_qt_translator)
        _qt_translator = None
    if code != "en":
        translator = QTranslator(app)
        path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        if translator.load(f"qtbase_{code}", path):
            app.installTranslator(translator)
            _qt_translator = translator
