# Daybook

A daily expense tracker that works as an app on your iPhone's Home Screen. Log an expense in a few taps, set a monthly budget and category limits, and see where your money goes.

Your expenses are stored only on your own phone. Nothing is sent to a server, and nobody who opens this website can see your data.

## What's in this folder

| File | What it does |
| --- | --- |
| `index.html` | The whole app |
| `manifest.webmanifest` | Tells the phone the app's name, colours and icons |
| `sw.js` | Lets the app open without an internet connection |
| `apple-touch-icon.png` | The Home Screen icon on iPhone and iPad |
| `icon-192.png`, `icon-512.png`, `icon-maskable-512.png` | Icons for Android and desktop browsers |

All files sit at the top level, with no folders, so you can upload them even from a phone.

## Put it online with GitHub Pages (free)

1. Sign in at [github.com](https://github.com), or create a free account.
2. Tap **+** (top right), then **New repository**. Name it `daybook`, choose **Public** (GitHub Pages is free for public repositories), and tap **Create repository**.
3. On the new repository page, choose **Add file → Upload files** (or the "uploading an existing file" link). Add all seven files listed above. Upload the files themselves, not the folder they came in.
4. Tap **Commit changes**.
5. Open the repository's **Settings → Pages**. Under **Build and deployment**, set **Source** to **Deploy from a branch**, choose the **main** branch and the **/ (root)** folder, then **Save**.
6. Wait a minute or two, then refresh the Pages settings. It shows your address, which looks like `https://YOUR-USERNAME.github.io/daybook/`.

## Add it to your iPhone

1. Open your address in **Safari**.
2. Tap **Share**. On iOS 26 it may be inside the **…** menu next to the address bar.
3. Tap **Add to Home Screen**, leave **Open as Web App** switched on, and tap **Add**.
4. Open Daybook from the Home Screen and set your budget there.

The Home Screen app keeps its own data, separate from Safari tabs. Start using it from the Home Screen icon, not from a Safari tab.

## Keep your data safe

Your expenses live on your phone only. Removing the app from your Home Screen, or clearing Safari's website data, can erase them.

- Every month or so, open **Plan → Back up data** and save the file to iCloud Drive or Files.
- On a new phone, install the app the same way, then use **Restore from a backup**. Restoring never creates duplicates, so it's safe to restore the same file twice.
- **Export as CSV** gives you a spreadsheet for Excel or Google Sheets.
- Never upload a backup file to this repository, because the repository is public.

## Updating the app

Upload the new `index.html` to the same repository (it replaces the old one) and commit. The app picks up the new version the next time you open it while online.

If you change the icons or `manifest.webmanifest`, also change the `VERSION` line at the top of `sw.js` (for example, `daybook-v1` to `daybook-v2`). Then remove the app from your Home Screen and add it again, because iOS keeps the old icon otherwise.

## If something goes wrong

- **404 page:** wait a few minutes after turning on Pages. Then check that `index.html` is at the top level of the repository, not inside a folder.
- **The app doesn't change after an update:** close it fully (swipe it away in the app switcher) and open it again while online.
- **Your data isn't there:** make sure you opened the Home Screen icon, not Safari. If you moved phones, restore your latest backup.
