# Translation languages

The authenticated `/api/v1/settings/translation/languages` endpoint supplies the
same catalog to chat language selection and project settings. Uzbek (`uz`) is a
default. Existing project/chat language codes remain selectable even if not in
the catalog. No existing language or provider setting is changed on deployment.

Admins can add a language in project settings, below the translation provider.
The code and display name are stored globally in `system_settings`; no migration,
frontend rebuild or restart is required. Re-adding the same code updates its name.
Codes use the provider's language code (for example `uz`, `pt-br`), max 10 characters
to match existing chat/project fields. Changing the catalog does not enable a
language model at the translation provider or change the provider itself.

Google Cloud Translation supports Uzbek with code `uz`:
https://cloud.google.com/translate/docs/languages
For other providers verify language availability in that provider/account or
installed LibreTranslate models. Provider failures surface as translation errors;
the original draft is not replaced by a fabricated translation.
