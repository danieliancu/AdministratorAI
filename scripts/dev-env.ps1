# Run from the project root, dot-sourced:  . .\scripts\dev-env.ps1
# Points the local .venv at the database and Redis running in Docker Compose.
# It sets the restricted application role only, never the owner or superuser passwords.

$values = @{}
Get-Content .env | Where-Object { $_ -match '^\s*[^#].*=' } | ForEach-Object {
    $name, $value = $_.Split('=', 2)
    $values[$name.Trim()] = $value.Trim()
}

$env:DJANGO_SETTINGS_MODULE = 'config.settings.dev'
$env:DJANGO_SECRET_KEY = $values['DJANGO_SECRET_KEY']
$env:DB_HOST = 'localhost'
$env:DB_USER = 'aai_app'
$env:DB_PASSWORD = $values['AAI_APP_PASSWORD']
$env:REDIS_URL = 'redis://localhost:6379/0'
$env:CACHE_REDIS_URL = 'redis://localhost:6379/1'
$env:MAIL_HOST = 'localhost'

& .\.venv\Scripts\Activate.ps1
