import { CopilotKit, CopilotSidebar } from "@copilotkit/react-core/v2";
import { SimulationPage } from "./pages/SimulationPage";

const runtimeUrl = import.meta.env.VITE_COPILOTKIT_RUNTIME_URL ?? "http://localhost:8000/api/copilotkit";

export default function App() {
  return (
    <CopilotKit runtimeUrl={runtimeUrl}>
      <SimulationPage />
      <CopilotSidebar
        agentId="default"
        labels={{
          modalHeaderTitle: "Campaign Copilot",
          chatInputPlaceholder: "Ask about intake, personas, sentiment, or benchmark...",
          welcomeMessageText:
            "Ask me to switch tabs, explain generated personas, summarize reactions, show red flags, compare the benchmark, or filter a segment."
        }}
      />
    </CopilotKit>
  );
}
