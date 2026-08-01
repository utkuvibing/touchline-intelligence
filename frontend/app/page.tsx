/**
 * M0 landing page.
 *
 * This is an async Server Component and does nothing but fetch: every rendering decision lives in
 * `HomeView`, which is synchronous and therefore unit-testable. Async Server Components are not
 * testable with Vitest, so keeping logic out of this file is what stops the page's claims — the
 * provisional notice, the attribution, the "not an estimate" wording — from becoming untested.
 *
 * Rendered per request: the data is small and public, and changes only when the ingestion is
 * re-run, so there is nothing a cached render would buy.
 */

import { HomeView } from "@/components/HomeView";
import {
  fetchAllShots,
  fetchConversionRate,
  type ConversionRate,
  type Shot,
} from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Home() {
  let shots: Shot[] = [];
  let total = 0;
  let rate: ConversionRate | null = null;
  let error: string | null = null;

  try {
    const [all, conversion] = await Promise.all([
      fetchAllShots(),
      fetchConversionRate(),
    ]);
    shots = all.shots;
    total = all.total;
    rate = conversion;
  } catch (cause) {
    error = cause instanceof Error ? cause.message : "unknown error";
  }

  return <HomeView shots={shots} total={total} rate={rate} error={error} />;
}
