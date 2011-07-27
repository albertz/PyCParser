#include <stdio.h>

int main(int argc, char** argv) {
	printf("Hello %s! (via printf)\n", "world");
	fprintf(stdout, "%s world%c (via fprintf)\n", "Hello", '!');

	printf("expr1 = %i\n", -1);
	printf("expr2 = %i\n", 1 > -1);

	{
		int i;
		for(i = 0; i < 10; ++i)
			printf("count1: %i\n", i);
	}
	
	{
		int i = -1;
		while(++i < 10)
			printf("count2: %i\n", i);
	}
	
	{
		int i = 0;
		do {
			printf("count3: %i\n", i++);
		} while(i < 10);
	}
	
	return 0;
}
