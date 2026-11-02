from django.db import migrations

RULE = (
    "\n7. Răspunzi EXCLUSIV din două surse: FAPTELE (datele acestei firme) și DOVEZILE "
    "(legislația din aplicație). Nu folosi cunoștințe generale, nici despre lege, fiscalitate "
    "sau economie, nici despre alte subiecte, chiar dacă știi răspunsul. Dacă răspunsul nu se "
    "află în aceste două surse, spune doar că nu ai găsit informația și lasă goale fact_ids, "
    "evidence_ids și suggested_actions. Trece în fact_ids și evidence_ids numai ce susține "
    "direct răspunsul."
)
ANCHOR = "\n\nCâmpurile răspunsului:"


def add_version(apps, schema_editor):
    prompts = apps.get_model("ai_gateway", "PromptTemplateVersion").objects
    current = prompts.get(operation_id="assistant.answer", is_active=True)
    # Text is immutable: a change is a new version, so old answers stay traceable.
    prompts.filter(pk=current.pk).update(is_active=False)
    prompts.create(
        operation_id="assistant.answer",
        version=current.version + 1,
        system_template=current.system_template.replace(ANCHOR, RULE + ANCHOR),
        user_template=current.user_template,
        is_active=True,
    )


class Migration(migrations.Migration):
    dependencies = [("ai_gateway", "0006_assistant_operation")]

    operations = [migrations.RunPython(add_version, migrations.RunPython.noop)]
