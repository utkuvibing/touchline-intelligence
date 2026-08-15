/**
 * Compatibility export for the original M0 component name.
 *
 * The route now renders the model-aware analyst view. Keeping this alias avoids an unnecessary
 * import seam for local consumers while ensuring the obsolete "no model" page is not reachable.
 */
export {
  AnalystView as HomeView,
  type AnalystViewProps as HomeViewProps,
  type ResourceState,
} from "@/components/AnalystView";
