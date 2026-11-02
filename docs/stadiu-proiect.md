# Administrator AI: stadiul proiectului

Actualizat la 2 noiembrie 2026. Cod pe GitHub: `danieliancu/AdministratorAI`, ramura `master`.

**Pe scurt:** M1, M2, M3, M5 și M6 sunt construite și testate. Rămân M4, M7 și M8. Aplicația nu este gata de producție.

## Ce s-a făcut

| Etapă | Stare | Ce nu este încă acoperit |
|---|---|---|
| M1 Fundația SaaS | Gata | Fără MFA, export sau ștergere de date. Rolurile membrilor nu se pot schimba |
| M2 AI Gateway și costuri | Gata, cu un prim apel real la OpenAI | Doar operația de diagnostic folosește un model real |
| M3 Infrastructură legislativă | Gata, dar baza fiscală nu e utilizabilă | Nu există texte consolidate, iar Codul Fiscal nu se poate obține din serviciul oficial |
| M5 Aplicația financiară | Gata, pe date de test | Niciun export contabil real încercat |
| M6 Asistent AI | Gata, încercat cu OpenAI real pe date fictive | Fără integrarea cu regulile fiscale (M4). Răspunsurile legale sunt limitate de lipsa textelor consolidate |

### M1: fundația SaaS
- Conturi, autentificare, verificare email, resetare parolă.
- Firme, roluri, invitații, setări și profil fiscal declarat de utilizator.
- Izolare între firme în baza de date (PostgreSQL RLS) și jurnal de audit care nu se poate modifica.
- Zona de superadmin și pagina publică, în română.

### M2: AI Gateway și costuri
- Singura cale către furnizorii AI, cu bugete, rezervări atomice și prețuri versionate.
- Consumul AI este vizibil doar superadminului, nu și firmelor.

### M3: infrastructură legislativă
- Registru de surse, conectori Portal Legislativ și ANAF, testați pe serviciile reale.
- Istoric de versiuni care nu se suprascrie și căutare după data la care se aplică legea.
- Toate sursele sunt dezactivate până la o verificare juridică a condițiilor de reutilizare.

### M5: aplicația financiară
- **Vânzări:** clienți, facturi, încasări separate de facturi, vânzări fără factură.
- **Cheltuieli:** înregistrări, documente justificative, cheltuieli recurente generate la cerere.
- **Stocuri:** produse, istoric de mișcări care nu se poate modifica, alerte de stoc redus.
- **Importuri CSV și Excel:** previzualizare, detectare duplicate, rândurile originale păstrate.
- **Prezentare generală și rapoarte:** cifre etichetate, grafic pe 12 luni, export CSV.

Limitele M5:
- Facturile au doar totaluri, fără linii, deci o vânzare nu scade stocul.
- Stornările sunt refuzate.
- Se acceptă doar RON.
- Un import nu se poate anula în bloc.

### M6: asistent AI
- Răspunde exclusiv din datele firmei și din legislația din aplicație.
- Cifrele sunt calculate de aplicație. Dacă modelul scrie un număr care nu există în date, răspunsul lui nu se afișează.
- Calculele de impozit sunt refuzate înainte de a ajunge la model.
- Căutare în istoric, filtre, întrebări sugerate, iar istoricul îl vede doar cel care a întrebat.
- Costurile AI apar la superadmin în lei, cu două zecimale, la cursul oficial BNR.

### Ultima verificare
- 601 teste trec, iar fluxul complet în browser trece.
- `ruff` este curat, iar `pip-audit` nu găsește vulnerabilități.
- **CI pe GitHub:** trece pe `master`, cu lint, teste, migrări, `pip-audit` și `gitleaks`.

## Ce mai avem

| Etapă | Conținut | De ce depinde |
|---|---|---|
| M4 | Reguli fiscale și calendar fiscal | Regulile rămân inactive până le aprobă un specialist fiscal |
| M7 | Stripe, ANAF și notificări | Chei Stripe, certificat ANAF |
| M8 | Pregătire pentru producție | Găzduire, validare juridică și fiscală |

M4 poate fi construit, dar regulile rămân inactive până la aprobarea specialistului fiscal. Cele 200 de întrebări de control pentru asistent cer tot un specialist fiscal.

## Decizii deschise

1. **Sursa textelor legislative consolidate.** Recomandare: începem cu importul manual din PDF-uri oficiale. Alternativele sunt acces cerut la Ministerul Justiției sau un furnizor licențiat.
2. **Vizibilitatea repo-ului.** Este public acum. Recomandare: îl facem privat. Codul conține conturile de dezvoltare `admin` și `superadmin`, cu parola `1234`.
3. **Ramura principală.** `master` este ramura de lucru. Pe GitHub trebuie setată ca implicită, apoi se poate șterge `milestone-1`.

## Ce trebuie furnizat

- Un specialist fiscal, pentru aprobarea regulilor și cele 200 de întrebări de control.
- O verificare juridică a condițiilor de reutilizare a surselor legislative și a trimiterii datelor firmelor către OpenAI.
- Exporturi reale din programele de contabilitate folosite de firme.
- Chei Stripe de test, certificat și acces OAuth ANAF.
- Găzduire și un furnizor de email pentru producție.

## Încercare locală

Deschide http://localhost:8000 și intră cu `admin` / `1234`. Firma demo are date fictive. Detaliile tehnice sunt în [implementation-progress.md](implementation-progress.md).
