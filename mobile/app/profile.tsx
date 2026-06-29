import { SettingsScreen } from "@/components/SettingsScreen";
import { useAppearanceController } from "@/state/appearance";

/** The Profile / Settings route (`/profile`). Opens from the header gear. */
export default function ProfileRoute() {
  const { setAppearance } = useAppearanceController();
  return <SettingsScreen onAppearanceChange={setAppearance} />;
}
