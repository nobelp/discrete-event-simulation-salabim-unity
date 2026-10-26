// Integration check of the real C# process bridge, not an editor/runtime UI test.
using System;
using System.IO;
using System.Reflection;
using Newtonsoft.Json.Linq;
class Program {
 static int Main(string[] args) {
  string root=Path.GetFullPath(args[0]);
  string input=Path.Combine(root,"examples","kx-unity-zones.json");
  string output=Path.Combine(root,"results","csharp-bridge.json");
  var method=typeof(KxSimulationPanel).GetMethod("Execute",BindingFlags.NonPublic|BindingFlags.Static);
  string summary=(string)method.Invoke(null,new object[]{Path.Combine(root,".venv","Scripts","python.exe"),root,input,output});
  var result=JObject.Parse(File.ReadAllText(output));
  if((int)result["completed"]!=3||(int)result["unfinished"]!=1)throw new Exception("Incorrect bridge results");
  bool rejected=false;
  try {method.Invoke(null,new object[]{Path.Combine(root,".venv","Scripts","python.exe"),root,Path.Combine(root,"examples","kx-backpressure.json"),output});}
  catch(TargetInvocationException e) {rejected=e.InnerException is InvalidOperationException;}
  if(!rejected)throw new Exception("Bad contract was not reported as process failure");
  Console.WriteLine("C# bridge integration passed: 3 complete, 1 unfinished; invalid contract rejected.");
  return 0;
 }
}
