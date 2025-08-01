# Internationalization (i18n) Guide for AFHArchive

## Current Setup

The application supports internationalization using Flask-Babel with Crowdin integration. Currently, English is the primary language, with infrastructure ready for additional languages via Crowdin.

## Crowdin Integration (Recommended)

### File-Based Project Setup in Crowdin:
- **Project Type**: File-based
- **Source File**: `app/translations/messages.pot`
- **Translation Pattern**: `app/translations/%two_letters_code%/LC_MESSAGES/messages.po`
- **File Format**: Gettext PO

### Crowdin Workflow:
1. Extract messages: `C:/Users/josha/AppData/Local/Microsoft/WindowsApps/python3.13.exe translations.py extract`
2. Upload `messages.pot` to Crowdin
3. Translators work in Crowdin interface
4. Download completed translations
5. Commit translation files to Git
6. Compile: `C:/Users/josha/AppData/Local/Microsoft/WindowsApps/python3.13.exe translations.py compile`
7. Enable language in `app/__init__.py`

## Manual Translation Process (Alternative)

## Manual Translation Process (Alternative)

### 1. Update Flask Configuration

In `app/__init__.py`, add the new language to the `LANGUAGES` dictionary:

```python
app.config['LANGUAGES'] = {
    'en': 'English',
    'ru': 'Русский',
    'es': 'Español',    # Add new languages here
    'fr': 'Français',
    # etc.
}
```

### 2. Extract Messages (if new strings were added)

Run this command to extract all translatable strings:

```bash
C:/Users/josha/AppData/Local/Microsoft/WindowsApps/python3.13.exe translations.py extract
```

### 3. Initialize New Language

To create translation files for a new language (e.g., Spanish):

```bash
C:/Users/josha/AppData/Local/Microsoft/WindowsApps/python3.13.exe translations.py init es
```

This creates: `app/translations/es/LC_MESSAGES/messages.po`

### 4. Translate the Messages

1. Open the `.po` file for the language (e.g., `app/translations/es/LC_MESSAGES/messages.po`)
2. Fill in the `msgstr` fields with translations
3. Example:
   ```
   msgid "Home"
   msgstr "Inicio"
   
   msgid "Browse"
   msgstr "Explorar"
   ```

### 5. Compile Translations

After adding translations, compile them:

```bash
C:/Users/josha/AppData/Local/Microsoft/WindowsApps/python3.13.exe translations.py compile
```

This creates `.mo` files that Flask uses.

### 6. Update Existing Translations

When new translatable strings are added to the code:

1. Extract messages: `C:/Users/josha/AppData/Local/Microsoft/WindowsApps/python3.13.exe translations.py extract`
2. Update existing translations: `C:/Users/josha/AppData/Local/Microsoft/WindowsApps/python3.13.exe translations.py update`
3. Edit the `.po` files to add new translations
4. Compile: `C:/Users/josha/AppData/Local/Microsoft/WindowsApps/python3.13.exe translations.py compile`

## Translation Commands Summary

- `C:/Users/josha/AppData/Local/Microsoft/WindowsApps/python3.13.exe translations.py extract` - Extract strings from code
- `C:/Users/josha/AppData/Local/Microsoft/WindowsApps/python3.13.exe translations.py init <lang>` - Initialize new language
- `C:/Users/josha/AppData/Local/Microsoft/WindowsApps/python3.13.exe translations.py update` - Update existing translations
- `C:/Users/josha/AppData/Local/Microsoft/WindowsApps/python3.13.exe translations.py compile` - Compile translations

## File Structure

```
app/
├── translations/
│   ├── messages.pot          # Template file (generated)
│   ├── en/
│   │   └── LC_MESSAGES/
│   │       ├── messages.po   # English translations
│   │       └── messages.mo   # Compiled (generated)
│   └── ru/
│       └── LC_MESSAGES/
│           ├── messages.po   # Russian translations
│           └── messages.mo   # Compiled (generated)
```

## Making Strings Translatable

In templates, wrap strings with `{{ _('String to translate') }}`:

```html
<h1>{{ _('Welcome to AFHArchive') }}</h1>
<p>{{ _('Browse our collection') }}</p>
```

In Python code, import and use the `_` function:

```python
from flask_babel import _

flash(_('File uploaded successfully'))
```

## Language Selector

The language selector in the navigation will automatically appear when more than one language is configured. Users can switch languages, and their preference is stored in the session.

## Notes for Translators

- Keep HTML tags intact when they appear in strings
- Maintain placeholder formatting like `%(variable)s`
- Consider cultural context, not just literal translations
- Test the UI after adding translations to ensure text fits properly
