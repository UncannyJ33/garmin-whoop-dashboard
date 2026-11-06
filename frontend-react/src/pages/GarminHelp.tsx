/**
 * /help/garmin-export — public help page with Garmin Connect export instructions.
 *
 * Accessible without authentication so it can be opened before signing in.
 * Two export paths:
 *   1. Activities CSV (quick, just the workout list)
 *   2. Full account ZIP (comprehensive — includes all data types)
 */
import { Link } from 'react-router-dom'

function Step({ n, children }: { n: number; children: React.ReactNode }) {
  return (
    <li className="flex gap-3">
      <span className="flex-shrink-0 w-6 h-6 rounded-full bg-blue-600 text-white text-xs
                       font-bold flex items-center justify-center mt-0.5">
        {n}
      </span>
      <span className="text-slate-300 text-sm leading-relaxed">{children}</span>
    </li>
  )
}

function Mono({ children }: { children: React.ReactNode }) {
  return <span className="font-mono text-xs bg-slate-700 px-1.5 py-0.5 rounded">{children}</span>
}

function Steps({ steps }: { steps: React.ReactNode[] }) {
  return (
    <ol className="space-y-3">
      {steps.map((content, i) => (
        <Step key={i} n={i + 1}>{content}</Step>
      ))}
    </ol>
  )
}

function Section({
  title,
  badge,
  children,
}: {
  title: string
  badge?: string
  children: React.ReactNode
}) {
  return (
    <div className="rounded-2xl bg-slate-800/60 border border-slate-700 p-6 space-y-4">
      <div className="flex items-center gap-3">
        <h2 className="text-base font-semibold text-slate-100">{title}</h2>
        {badge && (
          <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-blue-900/60
                           text-blue-300 border border-blue-700">
            {badge}
          </span>
        )}
      </div>
      {children}
    </div>
  )
}

export function GarminHelp() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 px-4 py-10">
      <div className="max-w-2xl mx-auto space-y-8">

        {/* Back nav */}
        <Link
          to="/settings"
          className="inline-flex items-center gap-1.5 text-sm text-slate-400
                     hover:text-slate-200 transition-colors"
        >
          ← Back to Settings
        </Link>

        {/* Header */}
        <div className="space-y-1">
          <h1 className="text-2xl font-bold text-slate-100">
            How to export from Garmin Connect
          </h1>
          <p className="text-sm text-slate-400">
            There are two ways to get your Garmin data into PulseEngine.
            The Activities CSV is the fastest; the full account ZIP is the most complete.
          </p>
        </div>

        {/* Method 1 — Activities CSV */}
        <Section title="Method 1 — Activities CSV" badge="Fastest">
          <p className="text-sm text-slate-400">
            Exports the workout list as a spreadsheet. Quick to download and works with
            any date range filter. Best for most users.
          </p>
          <Steps
            steps={[
              <>
              Open{' '}
              <Mono>connect.garmin.com</Mono>{' '}
              and sign in.
              </>,
              <>
              Click <strong className="text-slate-200">Activities</strong> in the top navigation.
              </>,
              <>
              Optionally filter by date range using the calendar on the left sidebar.
              </>,
              <>
              Click the <strong className="text-slate-200">export icon</strong>{' '}
              (⬇ arrow or three-dot menu) near the top-right of the activity list
              and choose <strong className="text-slate-200">Export to CSV</strong>.
              </>,
              <>
              Save the downloaded <Mono>Activities.csv</Mono> file.
              </>,
              <>
              Upload it in PulseEngine via{' '}
              <Link to="/settings" className="text-blue-400 hover:text-blue-300 underline">
                Settings → Garmin → Import
              </Link>.{' '}
              Select the distance unit that matches your Garmin Connect settings
              (miles or kilometres).
              </>,
            ]}
          />
          <div className="rounded-xl bg-amber-950/40 border border-amber-800/60 px-4 py-3
                          text-xs text-amber-300 space-y-1">
            <p className="font-medium">Note on training load</p>
            <p>
              Garmin's CSV export only includes Training Stress Score (TSS) for
              power-meter cycling. For all other activity types, PulseEngine derives
              a proxy value from{' '}
              <em>Aerobic Training Effect × duration</em>.
              This is noted in the import result.
            </p>
          </div>
        </Section>

        {/* Method 2 — Full account export */}
        <Section title="Method 2 — Full Account Export (ZIP)" badge="Most complete">
          <p className="text-sm text-slate-400">
            Downloads a ZIP archive containing all of your Garmin data — activities,
            daily summaries, sleep, HRV, and more. The file can be large (several GB for
            multi-year histories) and Garmin may take up to 24 hours to prepare it.
          </p>
          <Steps
            steps={[
              <>
              Open{' '}
              <Mono>connect.garmin.com</Mono>{' '}
              and sign in.
              </>,
              <>
              Click your <strong className="text-slate-200">profile icon</strong> in the
              top-right corner, then choose{' '}
              <strong className="text-slate-200">Account Settings</strong>.
              </>,
              <>
              Scroll to <strong className="text-slate-200">Export Your Data</strong> and
              click <strong className="text-slate-200">Request Data Export</strong>.
              </>,
              <>
              Garmin will email you when the export is ready (usually within a few hours).
              Follow the link in the email to download the ZIP.
              </>,
              <>
              Upload the <Mono>.zip</Mono>{' '}
              file directly in PulseEngine (up to 50 MB).
              If your archive is larger, extract the{' '}
              <Mono>DI_CONNECT/DI-Connect-Fitness/</Mono>{' '}
              folder and upload individual JSON files instead.
              </>,
            ]}
          />
        </Section>

        {/* Method 3 — JSON */}
        <Section title="Method 3 — JSON file (advanced)">
          <p className="text-sm text-slate-400">
            If you've extracted the ZIP or have a{' '}
            <Mono>summarizedActivities.json</Mono>{' '}
            from a Garmin API dump, you can upload that file directly.
            PulseEngine detects the{' '}
            <Mono>.json</Mono>{' '}
            extension and imports activity records automatically.
          </p>
        </Section>

        {/* FAQ */}
        <Section title="Common questions">
          <dl className="space-y-4 text-sm">
            <div>
              <dt className="font-medium text-slate-200 mb-1">
                Can I upload the same file more than once?
              </dt>
              <dd className="text-slate-400">
                Yes. Re-uploads are idempotent — existing activities are matched by
                activity ID (ZIP/JSON) or by activity type + start time (CSV), so
                duplicates are detected and skipped automatically.
              </dd>
            </div>
            <div>
              <dt className="font-medium text-slate-200 mb-1">
                What unit should I choose for the CSV?
              </dt>
              <dd className="text-slate-400">
                Match whatever unit is shown in your Garmin Connect Activity Settings.
                Go to{' '}
                <strong className="text-slate-300">Settings → Activity Settings → Units</strong>{' '}
                in Garmin Connect to check. Distance values are stored in metres internally;
                the toggle only affects how PulseEngine interprets the raw CSV numbers.
              </dd>
            </div>
            <div>
              <dt className="font-medium text-slate-200 mb-1">
                My export is larger than 50 MB. What do I do?
              </dt>
              <dd className="text-slate-400">
                For the CSV path, filter by a shorter date range in Garmin Connect before
                exporting (e.g., 6 months at a time) and upload in batches.
                For the ZIP path, extract the archive and upload the individual JSON files
                from the{' '}
                <Mono>DI_CONNECT/DI-Connect-Fitness/</Mono>{' '}
                folder one by one.
              </dd>
            </div>
          </dl>
        </Section>

        {/* CTA */}
        <div className="text-center pt-2">
          <Link
            to="/settings"
            className="inline-block bg-blue-600 hover:bg-blue-500 text-white text-sm
                       font-medium rounded-xl px-5 py-2.5 transition-colors"
          >
            Go to Settings to upload
          </Link>
        </div>
      </div>
    </div>
  )
}
