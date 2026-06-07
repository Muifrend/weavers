import { CopilotKit, CopilotSidebar } from "@copilotkit/react-core/v2";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { SimulationPage } from "./pages/SimulationPage";

const runtimeUrl = import.meta.env.VITE_COPILOTKIT_RUNTIME_URL ?? "http://localhost:8000/api/copilotkit";

export default function App() {
  return (
    <ErrorBoundary>
      <CopilotKit runtimeUrl={runtimeUrl}>
        <SimulationPage />
        <CopilotSidebar
          agentId="default"
          labels={{
            modalHeaderTitle: "Campaign Copilot",
            chatInputPlaceholder: "Generate a set, choose one, run the analysis...",
            welcomeMessageText:
              "I can drive the whole flow: \"generate 12 personas for Texas\", \"use the California set\", then \"run the analysis\". I can also explain reactions, show red flags, compare the benchmark, or filter a segment."
          }}
        />
      </CopilotKit>
    </ErrorBoundary>
  );
}
