# Publication and sign-in handoff (nothing sent)

## GitHub

Intended public repository: **https://github.com/demir-sama/rowverdict**.
The local Git repository is complete; this document is not proof of publication.

The available `cursor-github` namespace has no create-repository, create-file or
push-files operation. Source-control guidance explicitly confirms inline tools
cannot commit repository files or create a GitHub repository. Cloud agents were
not used, as requested. The box's previously tested `GH_TOKEN` is invalid.

After the owner approves public publication, use normal CLI sign-in. Do not paste
a token into chat or borrow connector/browser credentials:

```bash
# Run interactively; existing invalid token env vars otherwise override gh's login.
env -u GH_TOKEN -u GITHUB_TOKEN gh auth login --hostname github.com --git-protocol https --web
# Complete the device/browser approval under demir-sama. Never record secrets.
env -u GH_TOKEN -u GITHUB_TOKEN gh auth status
```

Then, only with permission to create this exact public repository:

```bash
cd /workspace/hackathons/hermes-plugin/rowverdict
env -u GH_TOKEN -u GITHUB_TOKEN gh repo create demir-sama/rowverdict --public --source=. --remote=origin --push
```

If `origin` was already set, create the empty repo at `https://github.com/new`
(owner `demir-sama`, name `rowverdict`, public, **no** auto-created README/license),
then `git push -u origin main` through authenticated Git. Do not force-push over
someone else's content. Confirm the public tree's commit equals the local pinned
commit before using the prepared catalog file. If the owner commits screenshots
later, regenerate the pin/diff against the new HEAD and re-run validation.

Do not open the catalog PR, post on X or submit the hackathon form until the owner
approves each exact external action. The catalog pack is prepared alongside this
repo under `../catalog-prepared/` after the source commit is created.

## Free model: normal sign-in required

Real endpoint attempts were made with the registered native tool schema and only
synthetic fixture context. No credential was available through Hermes's supported
secret accessor. Nous returned **HTTP 402**, OpenRouter **HTTP 401**. No real
model-generated tool call is verified. A zero-priced model listing is not a live
inference success and the 402 does not prove free entitlement for this account.

### Nous Portal (preferred)

1. Open **https://portal.nousresearch.com** and use normal account sign-in/sign-up.
2. In the active isolated Hermes profile, run `hermes auth add nous --type oauth --no-browser`.
3. Open the **exact verification URL printed by that command** and approve its
   device code. It is issued at runtime, so no fixed verification code/URL is invented here.
4. Run `hermes model`; select **Nous Research**, then `stepfun/step-3.7-flash:free`
   if the account's current picker offers it. Confirm the current $0 price before calling.
5. Ask Hermes to invoke `rowverdict_inspect` on the synthetic fixture. Verify the
   recorded native tool call returns `input_rows: 10000`; don't accept a prose answer.
6. If the portal requests billing or a paid plan, stop. Do not add a card or buy credits.

### OpenRouter alternative

1. Normal sign-in at **https://openrouter.ai**; key management is
   **https://openrouter.ai/settings/keys**.
2. Generate/use a key through normal user-controlled setup; no key in chat, CLI
   flags, screenshots or committed files. `hermes auth add openrouter --type api-key`
   prompts securely. Do not read auth stores directly.
3. `hermes model`: choose OpenRouter and `openrouter/free` (or an explicitly
   zero-priced tool-capable free model shown now). Free accounts can be rate-limited
   or require eligibility. Stop rather than paying if free access is refused.
4. Run the same one-tool synthetic inspect smoke. Export still needs actual host
   human approval independently of inference.

Neither provider sign-in blocks deterministic tests or the offline demo.

## Visual QA / screenshots still to do

The real stable dashboard was built and its actual host-mounted plugin routes,
authentication and JS/CSS assets tested. The executor's tool catalog has no browser,
desktop interaction or screenshot-delegation tool. It did not drive a browser from
Shell or manufacture a dashboard screenshot.

The parent can use its browser/desktop tool on the running local dashboard and
capture `docs/dashboard-review.png` after checking tabs, scrolling, keyboard
navigation, refresh and the real native approval flow. The existing
`docs/cli-evidence.png` is honestly labeled rendered output from the real offline
core demonstration, not a live screen capture.
