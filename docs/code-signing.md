# Signing the Windows app

Windows shows **"Windows protected your PC"** for Clippy's installer because it isn't signed with a code-signing
certificate. Signing proves who made the file and that nobody changed it. It needs a certificate from a trusted
authority, so it can't be done in the code alone.

## Where it stands

Clippy applied to SignPath Foundation on 18 November 2026. On 19 November they said no for now: the Foundation
program is for projects with established public trust and visibility (GitHub stars, forks, contributors, articles,
discussions on Reddit, YouTube and the like, or institutional backing), and they invited Clippy to apply again once
it has broader recognition. Their paid plan was offered instead; Clippy stays with free options.

Until then: each release can be submitted to Microsoft as described at the end ("Until then"), and Windows'
SmartScreen also warns less as more people download a release.

## The free route: SignPath Foundation

[SignPath Foundation](https://signpath.org/) signs open-source projects for free, straight from GitHub Actions.
Clippy fits: MIT license, public repository, built on GitHub Actions, with earlier releases. The certificate is
issued to SignPath Foundation, so Windows shows it as the publisher.

What the project owner does (once):

1. Turn on two-factor sign-in for your GitHub account (SignPath requires it for everyone on the project).
2. Apply at [signpath.org](https://signpath.org/) with the repository link, `https://github.com/StormAmdam/clippy`,
   and what gets signed: `Clippy.exe` and `Clippy-Setup-<version>-win64.exe`, built by
   `.github/workflows/windows-app.yml` on `windows-latest`.
3. When they approve it, they give you an **organization ID**, a **project slug**, a **signing policy slug** and an
   **API token**. Add the API token to the repository as a secret named `SIGNPATH_API_TOKEN` (GitHub → Settings →
   Secrets and variables → Actions), and send the other three to whoever wires up the workflow.

SignPath's conditions for the project page are already in the README: the **Code signing policy** section (their
attribution line and who commits, reviews and approves) and the **Privacy** section. Signed releases also carry the
attribution line *"Free code signing provided by SignPath.io, certificate by SignPath Foundation"* in their release
notes.

The application form, field by field:

| Field | What to put |
|---|---|
| Project Name | Clippy |
| Repository URL | https://github.com/StormAmdam/clippy |
| Homepage URL | https://github.com/StormAmdam/clippy |
| Download URL | https://github.com/StormAmdam/clippy#install |
| Privacy Policy URL | https://github.com/StormAmdam/clippy#privacy |
| Wikipedia URL | (empty) |
| Tagline | Clippy turns long videos into captioned vertical shorts on your own PC, with a local AI that picks the best moments. |

## What changes in the workflow

The build signs in two rounds, because the installer contains `Clippy.exe`:

1. Build the app folder, upload `Clippy.exe` as an artifact, have SignPath sign it, put the signed one back.
2. Build the installer and portable zip from that folder, upload the installer, have SignPath sign it, attach the
   signed files to the release.

SignPath's GitHub action (`signpath/github-action-submit-signing-request`) does each round. It's only added once the
details from step 3 exist, so it can be tested for real before a release depends on it.

## Until then

A new signature also starts with no reputation, so Windows may still warn for a while after signing begins. Meanwhile
a release can be submitted to Microsoft as a false positive at
[microsoft.com/wdsi/filesubmission](https://www.microsoft.com/wdsi/filesubmission) (sign in, choose
"Software developer", upload the installer). That often clears the warning for that one file, and it has to be done
for each release.
