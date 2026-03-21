/**
 * Privacy Policy — public page, no auth required.
 * Standalone layout (no sidebar/header) with dark theme and readability-optimised typography.
 */

const LAST_UPDATED = 'March 16, 2026'

export function Privacy() {
  return (
    <div className="min-h-screen bg-surface-bg px-4 py-12">
      <div className="mx-auto max-w-[720px]">

        {/* Back link */}
        <a
          href="https://pulsebuilt.net"
          className="inline-flex items-center gap-1.5 text-sm text-slate-400 hover:text-slate-200 transition-colors mb-10"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
          Back
        </a>

        {/* Header */}
        <div className="mb-10">
          <p className="text-xs font-semibold uppercase tracking-widest text-brand mb-2">PulseEngine</p>
          <h1 className="text-3xl font-bold text-slate-100 mb-2">Privacy Policy</h1>
          <p className="text-sm text-slate-400">Last updated: {LAST_UPDATED} · Operated by Pulse Built</p>
        </div>

        {/* Body */}
        <div className="prose-policy">

          <section>
            <p>
              PulseEngine ("we", "our", "the app") is a fitness analytics dashboard that
              integrates data from wearable devices. This policy explains what data we collect,
              how we use it, and your rights.
            </p>
          </section>

          <section>
            <h2>What Data We Collect</h2>
            <ul>
              <li>
                <strong>Account information</strong> — email address and encrypted password
                when you create an account.
              </li>
              <li>
                <strong>Whoop data</strong> — recovery scores, heart rate variability, resting
                heart rate, sleep stages and duration, workout strain, and other physiological
                metrics accessed via the Whoop API with your explicit authorization.
              </li>
              <li>
                <strong>Garmin data</strong> — workout details, running dynamics, daily health
                summaries, and other fitness metrics — provided either through manual CSV upload
                or optional credential-based sync with your explicit consent.
              </li>
              <li>
                <strong>Usage data</strong> — sync timestamps and basic app interaction data
                for troubleshooting.
              </li>
            </ul>
            <p>
              We do not collect location data, contacts, browsing history, or any data beyond
              what is described above.
            </p>
          </section>

          <section>
            <h2>How We Use Your Data</h2>
            <p>
              Your fitness data is used exclusively to power your personal PulseEngine
              dashboard — calculating readiness scores, generating training insights,
              identifying trends, and displaying your metrics. We do not use your data to
              train machine learning models, serve advertisements, or for any purpose other
              than providing you with the PulseEngine service.
            </p>
          </section>

          <section>
            <h2>How Your Data Is Stored and Protected</h2>
            <ul>
              <li>All data is stored in a PostgreSQL database hosted by Supabase with encryption at rest.</li>
              <li>All data transmission uses HTTPS (encryption in transit).</li>
              <li>Passwords are hashed using bcrypt and are never stored in plaintext.</li>
              <li>Whoop OAuth tokens are stored securely and can be revoked at any time.</li>
              <li>
                If you opt into Garmin credential storage, your email and password are
                encrypted using AES-128 symmetric encryption (Fernet) before being written
                to the database. Unlike a password hash, this encryption is reversible —
                the server decrypts your credentials only when performing background syncs
                on your behalf. This is a technical requirement of the Garmin integration,
                which has no OAuth flow. The encryption key is stored separately from the
                database. You can remove your stored Garmin credentials at any time from
                the Settings page.
              </li>
              <li>Each user's data is isolated — you can only access your own data.</li>
            </ul>
          </section>

          <section>
            <h2>Data Sharing</h2>
            <p>
              We do not sell, rent, or share your personal or health data with any third party.
              Your data is accessed only by the PulseEngine service to provide functionality
              to you. The only external services that interact with your data are:
            </p>
            <ul>
              <li>Whoop API (to fetch your authorized data)</li>
              <li>Garmin Connect (if you opt into credential-based sync)</li>
              <li>Supabase (database hosting provider, subject to their security practices)</li>
            </ul>
          </section>

          <section>
            <h2>Your Rights</h2>
            <p>You have the right to:</p>
            <ul>
              <li>Access all data we store about you.</li>
              <li>Export your data in CSV format.</li>
              <li>
                Delete your account and all associated data — email{' '}
                <a href="mailto:privacy@pulsebuilt.net">privacy@pulsebuilt.net</a>{' '}
                to request account deletion (self-serve deletion is coming soon).
              </li>
              <li>
                Disconnect your Whoop or Garmin integration at any time from the Settings page.
              </li>
              <li>
                Revoke PulseEngine's access to your Whoop data through your Whoop app settings.
              </li>
            </ul>
          </section>

          <section>
            <h2>Data Retention</h2>
            <p>
              Your data is retained for as long as your account is active. If you delete
              your account, all associated data is permanently removed from our systems
              within 30 days.
            </p>
          </section>

          <section>
            <h2>Changes to This Policy</h2>
            <p>
              We may update this policy as the product evolves. Material changes will be
              communicated via the app or email. The "last updated" date at the top reflects
              the most recent revision.
            </p>
          </section>

          <section>
            <h2>Contact</h2>
            <p>
              For privacy questions or data requests:{' '}
              <a href="mailto:privacy@pulsebuilt.net">privacy@pulsebuilt.net</a>
            </p>
          </section>

        </div>
      </div>
    </div>
  )
}
