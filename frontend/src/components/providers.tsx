"use client";

/*
  Shared client-side data layer.

  Every screen reads the same dashboard / unified-insight / action payloads,
  and a merchant action taken on one screen has to be visible on all of them
  at once, so the fetching and the action state live here rather than per
  page.

  Two actions now, not one: launching a campaign and raising a restock alert.
  Both refresh the dashboard afterwards, because both change what the home
  screen should say.
*/

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { ApiError, api } from "@/lib/api";
import type {
  ActionPlan,
  ActionProjection,
  Campaign,
  Dashboard,
  RestockAlert,
  RootCauseAnalysis,
  ShopSummary,
  UnifiedPayload,
} from "@/types";

interface AppData {
  dashboard: Dashboard | null;
  unified: UnifiedPayload | null;
  shop: ShopSummary | null;
  plan: ActionPlan | null;
  rootCause: RootCauseAnalysis | null;
  loading: boolean;
  error: { message: string; hint?: string } | null;
  reload: () => Promise<void>;

  activeCampaign: Campaign | null;
  restockAlerts: RestockAlert[];
  launchedProjection: ActionProjection | null;
  restockProjection: ActionProjection | null;

  busy: boolean;
  actionError: string | null;
  launchCampaign: () => Promise<boolean>;
  createRestock: (product: string) => Promise<boolean>;
  resetDemo: () => Promise<void>;
}

const Ctx = createContext<AppData | null>(null);

export function AppDataProvider({ children }: { children: ReactNode }) {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [unified, setUnified] = useState<UnifiedPayload | null>(null);
  const [shop, setShop] = useState<ShopSummary | null>(null);
  const [plan, setPlan] = useState<ActionPlan | null>(null);
  const [rootCause, setRootCause] = useState<RootCauseAnalysis | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<{ message: string; hint?: string } | null>(null);

  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [launchedProjection, setLaunchedProjection] = useState<ActionProjection | null>(null);
  const [restockProjection, setRestockProjection] = useState<ActionProjection | null>(null);

  // Every state write happens after the await, so the mount effect below never
  // calls setState synchronously (which would cascade renders).
  const fetchAll = useCallback(async () => {
    try {
      const [d, u, s, p, rc] = await Promise.all([
        api.dashboard(),
        api.unifiedInsights(),
        api.shopSummary(),
        api.actions(),
        api.rootCause(),
      ]);
      setDashboard(d);
      setUnified(u);
      setShop(s);
      setPlan(p);
      setRootCause(rc);
      setError(null);
      if (d.active_campaign?.projection) {
        setLaunchedProjection(d.active_campaign.projection);
      }
    } catch (err) {
      const apiErr = err as ApiError;
      setError({ message: apiErr.message ?? "Something went wrong.", hint: apiErr.hint });
    } finally {
      setLoading(false);
    }
  }, []);

  // Called from retry buttons, where showing the spinner immediately is correct.
  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    await fetchAll();
  }, [fetchAll]);

  // Fetch-on-mount against a separate FastAPI service. The rule targets
  // synchronous setState cascades; every write here happens after an await.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void fetchAll();
  }, [fetchAll]);

  const launchCampaign = useCallback(async () => {
    const recommendation = plan?.campaign;
    if (!recommendation || !dashboard) return false;

    setBusy(true);
    setActionError(null);
    try {
      const result = await api.launchCampaign({
        merchant_id: dashboard.merchant.merchant_id,
        campaign_name: recommendation.name,
        cashback_amount: recommendation.config.cashback_amount,
        minimum_transaction: recommendation.config.minimum_transaction,
        start_time: recommendation.config.start_time,
        end_time: recommendation.config.end_time,
        target_segment: recommendation.config.target_segment,
      });
      setLaunchedProjection(result.projection);
      setDashboard((prev) => (prev ? { ...prev, active_campaign: result.campaign } : prev));
      // Re-read the plan so `already_active` and the primary action update.
      void api.actions().then(setPlan).catch(() => undefined);
      return true;
    } catch (err) {
      setActionError((err as ApiError).message ?? "Could not launch the campaign.");
      return false;
    } finally {
      setBusy(false);
    }
  }, [plan, dashboard]);

  const createRestock = useCallback(async (product: string) => {
    setBusy(true);
    setActionError(null);
    try {
      const result = await api.createRestockAlert(product);
      setRestockProjection(result.projection);
      setDashboard((prev) =>
        prev
          ? { ...prev, open_restock_alerts: [result.alert, ...prev.open_restock_alerts] }
          : prev,
      );
      void api.actions().then(setPlan).catch(() => undefined);
      return true;
    } catch (err) {
      setActionError((err as ApiError).message ?? "Could not create the restock alert.");
      return false;
    } finally {
      setBusy(false);
    }
  }, []);

  const resetDemo = useCallback(async () => {
    await api.resetDemo();
    setLaunchedProjection(null);
    setRestockProjection(null);
    await reload();
  }, [reload]);

  const value = useMemo<AppData>(
    () => ({
      dashboard,
      unified,
      shop,
      plan,
      rootCause,
      loading,
      error,
      reload,
      activeCampaign: dashboard?.active_campaign ?? null,
      restockAlerts: dashboard?.open_restock_alerts ?? [],
      launchedProjection,
      restockProjection,
      busy,
      actionError,
      launchCampaign,
      createRestock,
      resetDemo,
    }),
    [
      dashboard,
      unified,
      shop,
      plan,
      rootCause,
      loading,
      error,
      reload,
      launchedProjection,
      restockProjection,
      busy,
      actionError,
      launchCampaign,
      createRestock,
      resetDemo,
    ],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAppData(): AppData {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAppData must be used inside AppDataProvider");
  return ctx;
}
