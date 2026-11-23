# Run the private Aqua website on one Windows PC

Use this launcher to screen-share a fresh synthetic employee workspace. It includes Opal and Classic, a password account with an analytics grant, eight fictional sales tables, private notes and the analyst banking reports. Each launch starts with empty personal history.

## First run

Use 64-bit Windows, CPython 3.12 x64, Mozilla Firefox x64 installed under Program Files, and Docker Desktop running Linux containers. Allow Docker 3 GB of memory. The first run downloads a pinned PostgreSQL image if it is missing. Subsequent runs can use the cached images offline.

1. Check the SHA-256 of the outer employee ZIP against the delivery record. Extract it into a new folder. Open PowerShell in that folder.
2. Verify the components and extract the launcher.

   ```powershell
   py -3.12 -B -I verify_transfer.py
   Expand-Archive -LiteralPath .\presenter-demo.zip -DestinationPath .\presenter-demo
   ```

3. Start the website. Leave the terminal open while presenting.

   ```powershell
   py -3.12 -B -I .\presenter-demo\run.py
   ```

4. Enter the fictional email and temporary password shown in that terminal into the Firefox sign-in form. Screen-share the browser window. For Classic, close the demo and start another session with `--shell legacy`.
5. Choose **Rank groups**, select **trans**, group by **account_id**, count rows, rank highest first, request one rank and include ties. Review the draft, then press **Send**. Both accounts have 500 transactions. Open the saved result and its SQL. Try the analyst's fictional report and add a private context note.

The website and both databases stay on this computer. The local Firefox profile trusts the temporary certificate for this session. The guided ranking and built-in analyst reports work offline. Screen sharing works from this PC. Separate viewer devices require the prepared private HTTPS environment described in the sales presenter guide.

## Enable open-ended questions

To run regular analytics chat on this PC, use Aqua's selected Qwen 3 8B model. If you already have this model, use the local directory that contains its `blobs` and `manifests` folders. On standard Windows Ollama installations this is `$env:USERPROFILE\.ollama\models`. To populate a missing model, install Ollama for Windows and run `ollama pull qwen3:8b`. The model download is about 5.2 GB. [Ollama Qwen 3 8B release](https://ollama.com/library/qwen3:8b) · [Ollama storage locations](https://docs.ollama.com/faq)

```powershell
py -3.12 -B -I .\presenter-demo\run.py --model-cache "$env:USERPROFILE\.ollama\models"
```

Allow Docker Desktop 12 GB of RAM for the combined services. This command uses Docker's NVIDIA GPU support. Add `--cpu` to run on CPU if the PC has no compatible GPU. CPU inference can exceed Aqua's response deadline. The first model-connected launch downloads the pinned Ollama service image if necessary. Keep the model cache available for subsequent runs. The launcher verifies the model manifest and every referenced blob, then exposes those individual files read-only to a local Ollama service. The service shares the demo's isolated loopback network, with cloud inference disabled. The manifest SHA-256 starts with `500a1f067a9f`. If verification fails, select the folder containing the approved version.

## End the demo

Close the dedicated Firefox window or press Ctrl+C in the launcher terminal. The launcher removes its session containers, database contents and temporary Firefox profile. Docker keeps reusable image downloads. If Windows or Docker stops abruptly, restart Docker and use the session ID printed at startup.

```powershell
py -3.12 -B -I .\presenter-demo\run.py --cleanup YOUR_SESSION_ID
```

The cleanup command checks the exact session directory and ownership marker in the Windows temporary folder, and selects containers by the full session label and name. Close that session's Firefox window first. If Docker was unavailable, rerun the same command once Docker is ready.
