import { CopilotKit, CopilotSidebar } from "@copilotkit/react-core/v2";
import { SimulationPage } from "./pages/SimulationPage";

const runtimeUrl = import.meta.env.VITE_COPILOTKIT_RUNTIME_URL ?? "http://localhost:3001/api/copilotkit";

export default function App() {
  return (
    <CopilotKit runtimeUrl={runtimeUrl}>
      <SimulationPage />
      <CopilotSidebar
        agentId="default"
        defaultOpen={false}
        position="right"
        width="420px"
        labels={{
          modalHeaderTitle: "Campaign Copilot",
          chatInputPlaceholder: "Ask for a persona readout, red flag, or segment filter...",
          welcomeMessageText:
            "I can read the current simulation state, explain persona reactions, summarize movement, surface red flags, compare the Dobbs benchmark, and filter segments."
        }}
      />
    </CopilotKit>
  );
}
