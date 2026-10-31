// Ghidra headless script: decompile every function to a text file.
// usage: analyzeHeadless <proj> <name> -import foo.dll -postScript DumpDecomp.java <outfile>
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.FunctionManager;
import java.io.FileWriter;
import java.io.PrintWriter;

public class DumpDecomp extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        String out = (args.length > 0) ? args[0]
                : (System.getenv("TMPDIR") + "/decomp.txt");

        DecompInterface di = new DecompInterface();
        di.toggleCCode(true);
        di.toggleSyntaxTree(true);
        di.setSimplificationStyle("decompile");
        if (!di.openProgram(currentProgram)) {
            println("decompiler open failed");
            return;
        }

        PrintWriter pw = new PrintWriter(new FileWriter(out));
        pw.println("// program: " + currentProgram.getName());
        pw.println("// imagebase: " + currentProgram.getImageBase());
        FunctionManager fm = currentProgram.getFunctionManager();
        FunctionIterator it = fm.getFunctions(true);
        int n = 0;
        while (it.hasNext()) {
            Function f = it.next();
            if (f.isThunk()) continue;
            pw.println();
            pw.println("// ---- " + f.getName() + " @ " + f.getEntryPoint()
                    + "  params=" + f.getParameterCount());
            try {
                DecompileResults res = di.decompileFunction(f, 60, monitor);
                if (res != null && res.decompileCompleted()) {
                    pw.println(res.getDecompiledFunction().getC());
                } else {
                    pw.println("// DECOMP FAILED: " + (res == null ? "null" : res.getErrorMessage()));
                }
            } catch (Exception e) {
                pw.println("// EXCEPTION: " + e);
            }
            n++;
        }
        pw.close();
        di.dispose();
        println("decompiled " + n + " functions -> " + out);
    }
}
