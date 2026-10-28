import RequirePermission from "@/components/common/RequirePermission";

// Primer Equipo screen: the "… Formativo" roles don't hold `core.view_gps_upload`.
export default function GpsUploadLayout({ children }: { children: React.ReactNode }) {
  return <RequirePermission codename="core.view_gps_upload">{children}</RequirePermission>;
}
