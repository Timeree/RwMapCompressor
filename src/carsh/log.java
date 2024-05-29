package carsh;

public class log {
 public static synchronized void e(Object cla, Throwable e) {
  System.out.println(cla);
  e.printStackTrace();
 }
}
