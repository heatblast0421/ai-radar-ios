# Put AI Radar on your iPhone

This takes about 10–15 minutes the first time. You need your Mac, your iPhone, a USB cable, and your Apple ID (the same one you use for the App Store; no paid account needed).

The project is already on your Mac in **Claude → AI-Radar**.

---

## Step 1: Open Xcode and sign in with your Apple ID

1. Open **Xcode** (Applications folder). If it asks to install additional components or platforms (iOS), click **Install** and wait.
2. In the menu bar choose **Xcode → Settings… → Accounts**.
3. Click **+** at the bottom left → **Apple ID** → sign in.

You should see your name with a "Personal Team" underneath. Close the Settings window.

## Step 2: Open the AI Radar project

1. In Finder open **Claude → AI-Radar → ios**.
2. Double-click **AIRadar.xcodeproj**.

Xcode opens the project. The left sidebar shows a blue **AIRadar** icon at the top.

## Step 3: Let Xcode sign the app with your Apple ID

1. Click the blue **AIRadar** icon at the top of the left sidebar.
2. In the middle area, under **TARGETS**, click **AIRadar**.
3. Click the **Signing & Capabilities** tab.
4. Make sure **Automatically manage signing** is ticked.
5. In **Team**, choose **Your Name (Personal Team)**.

Expect a "Signing Certificate: Apple Development" line and no red errors.
If you see a red error about the bundle identifier ("not available" or "cannot be registered"), change **Bundle Identifier** to something unique, such as `com.arnit.airadar`, and press Return.

## Step 4: Connect and prepare your iPhone

1. Plug the iPhone into the Mac with the cable and unlock it.
2. If the iPhone asks **"Trust This Computer?"**, tap **Trust** and enter your passcode.
3. Turn on **Developer Mode** (needed once):
   1. On the iPhone, open **Settings → Privacy & Security**.
   2. Scroll to the bottom, tap **Developer Mode**, and switch it on.
   3. The iPhone restarts. After the restart, tap **Turn On** and enter your passcode.
   - If you don't see Developer Mode, do Step 5 once first (Xcode makes the option appear), then come back.

## Step 5: Install and run

1. At the top of the Xcode window, click the device selector (it may say "iPhone 16" or "Any iOS Device") and choose **your iPhone**.
2. Press the **▶ Run** button (or ⌘R).
3. The first time, Xcode may show "Preparing iPhone…" or "Copying shared cache…" for a few minutes. That's normal.

The AI Radar icon (a teal radar) appears on your iPhone and the app opens.

**If the iPhone says "Untrusted Developer":**
1. On the iPhone open **Settings → General → VPN & Device Management**.
2. Tap your Apple ID under "Developer App", then tap **Trust**.
3. Open AI Radar from the home screen.

## Step 6 (optional): Install without the cable next time

In Xcode: **Window → Devices and Simulators** → select your iPhone → tick **Connect via network**. As long as the Mac and iPhone are on the same Wi-Fi, they now appear in the device selector without the cable.

---

## Every 7 days: refresh the app

With a free Apple ID, Apple lets the app run for 7 days. After that it won't open (your data stays safe). To renew:

1. Open **AIRadar.xcodeproj** in Xcode.
2. Select your iPhone (cable or Wi-Fi) and press **▶ Run**.

That's it. Bookmarks and settings are kept.

To avoid this, the **Apple Developer Program** ($99/year) makes installs last a year and allows installing through TestFlight without Xcode. See [ACCOUNTS_AND_COSTS.md](ACCOUNTS_AND_COSTS.md).

## Using the app

- **Pulse**: today's briefing plus the unified feed. Switch between **For You** (tuned to your topics), **Latest** and **Trending**.
- **GitHub**: emerging repositories, fastest growing (measured), most stars, newest and new releases.
- **Research / Lab / Industry**: focused feeds, each with Top / Latest / Trending and topic filters.
- Tap any story for **Quick / Technical / Explore** explanations, the verified source text, links and "Why it's ranked here".
- Top bar: 🔍 search everything · 🔖 saved items · ⚙️ settings (topics, notifications, appearance, data-source health).
- Pull down on any screen to refresh.
