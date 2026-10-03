import Dashboard from "./dashboard";
import snapshot from "@/data/latest-selection.json";
import type { Snapshot } from "@/lib/types";

export default function Home() {
  return <Dashboard snapshot={snapshot as Snapshot} />;
}

