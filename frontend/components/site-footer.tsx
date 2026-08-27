import { STATS_BOMB_OPEN_DATA_URL } from "@/lib/site-links";

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="site-shell footer-grid">
        <div className="footer-attribution">
          <p className="footer-heading">Data</p>
          {/* eslint-disable-next-line @next/next/no-img-element -- SVG asset served unmodified from /public */}
          <img
            src="/statsbomb-logo.svg"
            alt="Hudl StatsBomb logo"
            width={140}
            height={19}
            loading="lazy"
            decoding="async"
          />
          <p className="muted" aria-label="Data provided by StatsBomb">
            Data provided by <strong>StatsBomb</strong> through the{" "}
            <a href={STATS_BOMB_OPEN_DATA_URL} target="_blank" rel="noreferrer">
              StatsBomb Open Data repository
            </a>
            , pinned to a fixed revision. This project does not reproduce StatsBomb&apos;s
            proprietary xG model.
          </p>
        </div>

        <div className="footer-col">
          <p className="footer-heading">Elsewhere</p>
          <div className="footer-links">
            <a
              href="https://github.com/utkuvibing/touchline-intelligence"
              target="_blank"
              rel="noreferrer"
            >
              Source repository
            </a>
            <a
              href="https://github.com/utkuvibing/touchline-intelligence/blob/main/MODEL_CARD.md"
              target="_blank"
              rel="noreferrer"
            >
              Full model card
            </a>
            <a
              href="https://touchline-intelligence-production.up.railway.app/docs"
              target="_blank"
              rel="noreferrer"
            >
              Model API reference
            </a>
            <a
              href="https://www.linkedin.com/in/utku-%C5%9Eahin-696397210/"
              target="_blank"
              rel="noreferrer"
            >
              Utku Şahin on LinkedIn
            </a>
          </div>
        </div>

        <div className="footer-col">
          <p className="footer-heading">Standing boundaries</p>
          <p>
            Historical shot-level predictions stay unpublished until the provider resolves the
            row-level data-use question in writing. The public API fails closed rather than
            approximating.
          </p>
          <p>
            Built by Utku Şahin. The ingest, model, serving layer, and this interface are one
            person&apos;s end-to-end work.
          </p>
        </div>
      </div>
    </footer>
  );
}
