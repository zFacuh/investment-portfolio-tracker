//! Shell de escritorio: abre la ventana y lanza el motor de datos en Python
//! (desktop/backend/server.py, que reutiliza core/) como proceso hijo.
//! Al cerrar la ventana, el proceso Python se cierra con ella.

use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use tauri::{Manager, RunEvent};

struct Backend(Mutex<Option<Child>>);

/// Ruta a desktop/backend/server.py. El motor en Python vive en el repositorio
/// (usa core/, config/ y data/), asi que se busca en este orden:
///   1. la variable IPT_REPO (carpeta raiz del repositorio clonado),
///   2. hacia arriba desde el .exe (si el .exe quedo dentro del repositorio),
///   3. la carpeta desde la que se compilo la app.
fn ruta_server() -> PathBuf {
    let en = |raiz: &std::path::Path| raiz.join("desktop").join("backend").join("server.py");
    if let Ok(r) = std::env::var("IPT_REPO") {
        let p = en(std::path::Path::new(&r));
        if p.exists() {
            return p;
        }
    }
    if let Ok(exe) = std::env::current_exe() {
        for dir in exe.ancestors().skip(1) {
            let p = en(dir);
            if p.exists() {
                return p;
            }
        }
    }
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("backend")
        .join("server.py")
}

/// Motor empaquetado con PyInstaller dentro del instalador (ver
/// desktop/scripts/build_engine.py). Si no esta (modo desarrollo), se usa Python.
fn motor_empaquetado(app: &tauri::App) -> Option<PathBuf> {
    if cfg!(debug_assertions) {
        return None; // `tauri dev`: siempre el codigo Python en vivo
    }
    let exe = app.path().resource_dir().ok()?.join("engine").join("ipt-engine.exe");
    exe.exists().then_some(exe)
}

fn lanzar_backend(app: &tauri::App) -> Option<Child> {
    let mut cmd = match motor_empaquetado(app) {
        // App instalada: los datos del usuario van a Documentos y la cache de
        // datos de mercado a la carpeta local de la app.
        Some(motor) => {
            let mut c = Command::new(&motor);
            c.current_dir(motor.parent().unwrap());
            // Si IPT_DATA_ROOT ya esta definida (ej. apuntando a un repositorio
            // clonado con tus datos), se respeta.
            if std::env::var_os("IPT_DATA_ROOT").is_none() {
                if let Ok(docs) = app.path().document_dir() {
                    c.env("IPT_DATA_ROOT", docs.join("Investment Portfolio Tracker"));
                }
            }
            if let Ok(local) = app.path().app_local_data_dir() {
                c.env("IPT_CACHE_DIR", local.join("cache"));
            }
            c
        }
        // Desde el codigo fuente: IPT_PYTHON permite elegir el interprete (ej. un
        // python.exe de un entorno virtual); por defecto, `py -3` en Windows.
        None => {
            let elegido = std::env::var("IPT_PYTHON").or_else(|_| std::env::var("FP_PYTHON"));
            let (exe, args): (String, Vec<String>) = match elegido {
                Ok(p) if !p.is_empty() => (p, vec![]),
                _ if cfg!(windows) => ("py".into(), vec!["-3".into()]),
                _ => ("python3".into(), vec![]),
            };
            let server = ruta_server();
            let mut c = Command::new(exe);
            c.args(args).arg(&server).current_dir(server.parent().unwrap());
            c
        }
    };

    let log = std::env::temp_dir().join("investment-portfolio-tracker-backend.log");
    let salida = std::fs::File::create(&log).ok();

    cmd.env("PYTHONIOENCODING", "utf-8")
        // El backend vigila este PID y se cierra solo si la app muere.
        .env("FP_PARENT_PID", std::process::id().to_string())
        .stdin(Stdio::null());
    if let Some(f) = salida {
        if let Ok(f2) = f.try_clone() {
            cmd.stdout(f).stderr(f2);
        }
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    match cmd.spawn() {
        Ok(child) => Some(child),
        Err(e) => {
            eprintln!("No se pudo lanzar el backend Python: {e}");
            None
        }
    }
}

fn cerrar_backend(child: &mut Child) {
    // `py` lanza a python.exe como hijo: hay que matar el arbol completo.
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        let _ = Command::new("taskkill")
            .args(["/PID", &child.id().to_string(), "/T", "/F"])
            .creation_flags(0x0800_0000)
            .status();
    }
    let _ = child.kill();
    let _ = child.wait();
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .setup(|app| {
            let hijo = lanzar_backend(app);
            app.manage(Backend(Mutex::new(hijo)));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error al iniciar la app");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            if let Some(mut child) = handle.state::<Backend>().0.lock().unwrap().take() {
                cerrar_backend(&mut child);
            }
        }
    });
}
