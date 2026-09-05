# Prompt for a Claude Code session on a Windows machine

Copy everything below the line into a Claude Code session opened in the
repo folder on the Windows PC (Surface Pro, Precision, any). It is
self-contained; the agent reads the repo docs for detail.

---

You are administering the Windows side of a laptop refurbishing line. Read `CLAUDE.md` and `restorer/BUILD_ON_WINDOWS.md` in this repo before doing anything, then follow BUILD_ON_WINDOWS.md section by section. Work on branch `v3-line-toolkit` (run `git fetch && git checkout v3-line-toolkit` if you are not on it).

Context: I resell batches of used Dell laptops (Vostro 7620, Vostro 15 7510, Vostro 7500). A Linux "Auditor" USB tests and erases each laptop. The "Restorer" USB you are building does a clean, unattended Windows 11 install with a retail out-of-box experience, stages Dell drivers during setup, and writes a per-unit report back to the stick. The PowerShell and batch files under `restorer/` were written on a Mac and have never run on Windows. Your job is to make them work here, build the sticks, and verify everything that can be verified without a laptop.

Safety rules, non-negotiable:
- Never run `auditor/audit.py`. It erases internal disks.
- Only write to removable volumes labelled `ESD-ISO`. Never format or partition anything yourself; I do the Rufus step by hand.
- Never commit anything under `restorer/Dell/Drivers`, `Downloads`, `BIOS`, `Catalog`, or `Reports`. They are git-ignored; keep them that way.
- If a script has a bug, make the smallest fix that works, test it again, then commit with a one-line message and push the branch. Do not restructure or "improve" beyond the fix.
- Ask me before anything that needs a download I have not already done, an elevated action outside the repo folder, or a purchase.

Do these in order and tell me the result of each before moving on:

1. Confirm you are on Windows, in an elevated PowerShell, on branch `v3-line-toolkit`, with `C:\Temp\Win11.iso` present (tell me if it is missing; I download it). Report free disk space.
2. Run the static checks in BUILD_ON_WINDOWS.md section 2 on `build_restorer.ps1`, `get_dell_drivers.ps1`, `Dell\Scripts\stage.ps1`, `Dell\Scripts\stage.cmd`, and `autounattend.xml`. Fix, commit, push anything that fails.
3. Run `.\get_dell_drivers.ps1 -ListOnly` and show me the package list per model with sizes. If a model matches nothing, find its exact display name in `Dell\Catalog\CatalogPC.xml` and retry. Then run the real download with `-IncludeBios`, then `.\build_restorer.ps1 -ExtractDups -ExtractOnly`. Tell me which packages did not extract so I can open them with 7-Zip, and how many `.inf` files each model folder has. Wi-Fi and Bluetooth must be present for every model; the rest is nice to have.
4. Tell me it is time to flash a stick with Rufus and give me the exact field values from BUILD_ON_WINDOWS.md section 4. Wait for me to say the stick is flashed and plugged in.
5. Run `.\build_restorer.ps1`, then every check in section 6 including the `stage.cmd <drive> -NoInstall` dry run. Show me the generated report. Delete the test report afterwards. Repeat 4 and 5 for each stick I hand you.
6. Give me the golden-unit checklist from section 7 in a compact form I can follow at the laptop. When I paste the contents of `Dell\Reports\<TAG>.txt` from a real install, interpret it: tell me whether activation, Secure Boot, and the driver set look right, and which Dell package to add for any device still listed as a problem.
7. Finish with a summary: what passed, what you changed (commit hashes), and what is still unverified.

Keep answers short and concrete. Commands in code blocks. When something needs my hands (Rufus, plugging sticks, the laptop), say so explicitly and stop until I confirm.
