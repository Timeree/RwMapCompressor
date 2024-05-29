
import java.io.File;
import java.util.Scanner;
import rust.rwmap;
import rust.ui;

public class test implements ui {
 public void end(Throwable e) {
 }
 public static void main(String[] args) throws Exception {
  Scanner in=new Scanner(System.in);
  while (true) {
   String path=in.nextLine();
   File f=new File(path);
   ui.pool.execute(new rwmap(f, new File(f.getParent(), "R_".concat(f.getName())), new test()));
  }
 }
}
